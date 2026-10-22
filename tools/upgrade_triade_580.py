#!/usr/bin/env python3
"""Tríade 5.8.0: diagnóstico y recuperación controlada.

Uso:
  python upgrade_triade_580.py --root /content/Triade
  python upgrade_triade_580.py --root /content/Triade --repair-leases
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, shutil, sqlite3, sys, time
from pathlib import Path

VERSION="5.8.0"

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def connect(db):
    c=sqlite3.connect(f"file:{db}?mode=ro", uri=True); c.row_factory=sqlite3.Row; return c

def q(c,sql,args=()):
    try:return [dict(r) for r in c.execute(sql,args).fetchall()]
    except Exception as e:return [{"error":str(e)}]

def report(root):
    db=root/"triade/memory/triade.db"
    out={"version":VERSION,"generated_at":now(),"root":str(root),"checks":{},"findings":[],"actions":[]}
    out["checks"]["root_exists"]=root.exists(); out["checks"]["db_exists"]=db.exists()
    if not db.exists(): out["findings"].append("database_missing"); return out
    c=connect(db)
    out["checks"]["sqlite_integrity"]=c.execute("PRAGMA integrity_check").fetchone()[0]
    out["checks"]["tables"]=c.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]
    out["counts"]={}
    for t in ["neurons","neuron_missions","neuron_evidence","neuron_education_sessions","neuron_education_events","autonomous_tasks","runs","worker_runs","metabolic_cycle","metabolic_needs","metabolic_receipts","runtime_health_snapshots","model_events","triade_capability_campaigns","triade_capability_attempts","improvement_proposals","improvement_canaries","trainable_adapters","federated_nodes"]:
        try: out["counts"][t]=c.execute(f"select count(*) from {t}").fetchone()[0]
        except Exception: out["counts"][t]=None
    out["task_status"]={r["status"]:r["n"] for r in q(c,"select status,count(*) n from autonomous_tasks group by status")}
    out["cycle_status"]={r["status"]:r["n"] for r in q(c,"select status,count(*) n from metabolic_cycle group by status")}
    h=q(c,"select * from runtime_health_snapshots order by snapshot_id desc limit 1")
    if h:
        out["latest_health"]={"snapshot_id":h[0].get("snapshot_id"),"state":h[0].get("state"),"reason":h[0].get("reason_json"),"created_at":h[0].get("created_at")}
        try: out["latest_health"]["metrics"]=json.loads(h[0].get("metrics_json") or "{}")
        except Exception: out["latest_health"]["metrics"]={}
    w=q(c,"select * from worker_runs order by id desc limit 1")
    if w: out["latest_worker"]=w[0]
    ev=q(c,"select role,provider,model_name,ok,error,quality_score,created_at from model_events order by id desc limit 10")
    out["recent_model_events"]=ev
    # Evidence-based findings
    h0=out.get("latest_health",{}); metrics=h0.get("metrics",{})
    if h0.get("state")=="stalled" or "queue_not_progressing" in str(h0.get("reason")): out["findings"].append("worker_queue_not_progressing")
    if out.get("latest_worker",{}).get("summary_json")=="{\"iterations\": 0}": out["findings"].append("worker_reports_zero_iterations")
    if out["task_status"].get("pending",0): out["findings"].append("pending_tasks_exist")
    if out["task_status"].get("dead_letter",0): out["findings"].append("dead_letter_tasks_exist")
    if any(e.get("ok")==0 for e in ev): out["findings"].append("recent_model_event_failed")
    if out["checks"]["sqlite_integrity"]!="ok": out["findings"].append("sqlite_integrity_failed")
    o=metrics.get("ollama",{})
    out["ollama"]={k:o.get(k) for k in ["ok","ollama_ok","models_available","latency_ms","fallback_mode","degraded_components"]}
    out["resources"]={k:metrics.get("resources",{}).get(k) for k in ["gpu","memory","hardware","warnings"]}
    c.close(); return out

def repair_leases(root):
    db=root/"triade/memory/triade.db"; stamp=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=db.with_name(f"triade.db.pre_5_8_0_{stamp}"); shutil.copy2(db,backup)
    changed=0
    with sqlite3.connect(db) as c:
        # Only release running tasks whose lease is explicitly expired; preserve all payloads.
        nowiso=now()
        rows=c.execute("select task_id from autonomous_tasks where status='running' and lease_expires_at is not null and lease_expires_at < ?",(nowiso,)).fetchall()
        for (tid,) in rows:
            c.execute("update autonomous_tasks set status='pending',worker_id=null,lease_acquired_at=null,lease_expires_at=null,heartbeat_at=null,updated_at=?,last_error=? where task_id=?",(nowiso,"recovered_by_triade_5.8.0",tid)); changed+=1
        c.commit()
    return {"backup":str(backup),"requeued_expired_leases":changed,"timestamp":stamp}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default="."); ap.add_argument("--repair-leases",action="store_true"); ap.add_argument("--output",default=None); a=ap.parse_args()
    root=Path(a.root).resolve(); r=report(root)
    if a.repair_leases:
        r["repair"]=repair_leases(root); r["post_repair"]=report(root)
    out=Path(a.output) if a.output else root/"runs"/f"triade_5.8.0_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(r,ensure_ascii=False,indent=2)); print(f"\nINFORME: {out}")
if __name__=="__main__": main()

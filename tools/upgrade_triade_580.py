"""Tríade 5.8.0: diagnóstico y recuperación controlada.

Uso:
  python upgrade_triade_580.py --root /content/Triade
  python upgrade_triade_580.py --root /content/Triade --repair-leases
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from pathlib import Path

VERSION="5.8.0"
# This tool is a diagnostic and optional recovery utility; it does not install code.

def now(): return dt.datetime.now(dt.UTC).isoformat()
def connect(db):
    c=sqlite3.connect(f"file:{db}?mode=ro", uri=True); c.row_factory=sqlite3.Row; return c

def q(c,sql,args=()):
    try:return [dict(r) for r in c.execute(sql,args).fetchall()]
    except sqlite3.Error as e:return [{"error":str(e)}]

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
        except sqlite3.Error: out["counts"][t]=None
    out["task_status"]={r["status"]:r["n"] for r in q(c,"select status,count(*) n from autonomous_tasks group by status")}
    out["cycle_status"]={r["status"]:r["n"] for r in q(c,"select status,count(*) n from metabolic_cycle group by status")}
    h=q(c,"select * from runtime_health_snapshots order by snapshot_id desc limit 1")
    if h:
        out["latest_health"]={"snapshot_id":h[0].get("snapshot_id"),"state":h[0].get("state"),"reason":h[0].get("reason_json"),"created_at":h[0].get("created_at")}
        try: out["latest_health"]["metrics"]=json.loads(h[0].get("metrics_json") or "{}")
        except (TypeError, ValueError): out["latest_health"]["metrics"]={}
        try:
            stamp=dt.datetime.fromisoformat(h[0]["created_at"])
            if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=dt.UTC)
            out["latest_health"]["snapshot_age_seconds"]=max(0.0,(dt.datetime.now(dt.UTC)-stamp).total_seconds())
        except (TypeError, ValueError, KeyError):
            out["latest_health"]["snapshot_age_seconds"]=None
    w=q(c,"select * from worker_runs order by id desc limit 1")
    if w:
        out["latest_worker"]=w[0]
        events=q(c,"""SELECT COALESCE(MAX(id),0) AS last_event_id,
                             COUNT(*) AS total_events,
                             COALESCE(SUM(CASE WHEN event_type='task_completed' THEN 1 ELSE 0 END),0) AS completed_events
                      FROM worker_events WHERE run_ref=?""",(w[0]["run_ref"],))
        if events and "error" not in events[0]:
            out["worker_progress"]={"run_ref":w[0]["run_ref"], **events[0]}
    ev=q(c,"select role,provider,model_name,ok,error,quality_score,created_at from model_events order by id desc limit 10")
    out["recent_model_events"]=ev
    # Evidence-based findings
    h0=out.get("latest_health",{}); metrics=h0.get("metrics",{})
    if h0.get("state")=="stalled" or "queue_not_progressing" in str(h0.get("reason")): out["findings"].append("worker_queue_not_progressing")
    # Running workers initialise this summary with 0 and finalise it on exit.
    # Do not label an active worker stalled solely from an unfinished summary.
    if out.get("latest_worker",{}).get("summary_json")=='{"iterations": 0}':
        if out["latest_worker"].get("status")=="running":
            out["findings"].append("worker_summary_not_final")
        else:
            out["findings"].append("worker_reports_zero_iterations")
    if out["task_status"].get("pending",0): out["findings"].append("pending_tasks_exist")
    if out["task_status"].get("dead_letter",0): out["findings"].append("dead_letter_tasks_exist")
    if any(e.get("ok")==0 for e in ev): out["findings"].append("recent_model_event_failed")
    if out["checks"]["sqlite_integrity"]!="ok": out["findings"].append("sqlite_integrity_failed")
    o=metrics.get("ollama",{})
    out["ollama"]={k:o.get(k) for k in ["ok","ollama_ok","models_available","latency_ms","fallback_mode","degraded_components"]}
    out["resources"]={k:metrics.get("resources",{}).get(k) for k in ["gpu","memory","hardware","warnings"]}
    c.close(); return out

def repair_leases(root):
    """Explicit offline-only recovery with a consistent SQLite/WAL backup."""
    db=root/"triade/memory/triade.db"
    status=report(root)
    health=status.get("latest_health",{})
    age=health.get("snapshot_age_seconds")
    heartbeat=health.get("metrics",{}).get("heartbeat_age_seconds")
    if (status.get("latest_worker",{}).get("status")=="running"
            and isinstance(age,(int,float)) and age<90
            and isinstance(heartbeat,(int,float)) and heartbeat<90):
        raise RuntimeError("Refusing lease repair while an active worker heartbeat is fresh. Stop the runtime safely first.")
    stamp=dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ%f")
    backup=db.with_name(f"triade.db.pre_5_8_0_{stamp}")
    with sqlite3.connect(db) as source, sqlite3.connect(backup) as target:
        source.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise RuntimeError("SQLite backup integrity check failed; leases untouched")
    changed=0
    with sqlite3.connect(db,timeout=20) as c:
        c.execute("BEGIN IMMEDIATE")
        nowiso=now()
        rows=c.execute("select task_id from autonomous_tasks where status='running' and lease_expires_at is not null and lease_expires_at < ?",(nowiso,)).fetchall()
        for (tid,) in rows:
            c.execute("update autonomous_tasks set status='pending',worker_id=null,lease_acquired_at=null,lease_expires_at=null,heartbeat_at=null,updated_at=?,last_error=? where task_id=? AND status='running'",(nowiso,"recovered_by_triade_5.8.0",tid))
            changed+=c.execute("SELECT changes()").fetchone()[0]
        c.commit()
    return {"backup":str(backup),"backup_integrity":"ok","requeued_expired_leases":changed,"timestamp":stamp}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default="."); ap.add_argument("--repair-leases",action="store_true"); ap.add_argument("--output",default=None); a=ap.parse_args()
    root=Path(a.root).resolve(); r=report(root)
    if a.repair_leases:
        r["repair"]=repair_leases(root); r["post_repair"]=report(root)
    out=Path(a.output) if a.output else root/"runs"/f"triade_5.8.0_{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}.json"; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(r,ensure_ascii=False,indent=2)); print(f"\nINFORME: {out}")
if __name__=="__main__": main()

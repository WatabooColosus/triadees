"""Fault injection into one owned handler of the unmodified normal WorkerLoop."""
from pathlib import Path
import sys, json, time, threading, multiprocessing as mp, hashlib, subprocess
from uuid import uuid4
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from triade.db import sqlite3
from triade.workers.worker_loop import WorkerLoop
from triade.workers.contracts import WorkerRunConfig
from triade.core.contracts import utc_now
TRIADE_ENTRYPOINT_KIND = "manual_diagnostic"

def main():
    origin = json.loads((ROOT / "reports/evolution/productive_learning_chain_v3.json").read_text(encoding="utf-8"))
    work = Path(origin["artifact_ref"]).resolve()
    if not work.is_relative_to(ROOT / "artifacts/evolution"):
        raise ValueError("experiment_scope")
    db = work / "learning.db"
    with sqlite3.connect(db) as c:
        row = c.execute("SELECT payload_json FROM neuron_education_events WHERE event_type='domain_certification_completed' AND json_extract(payload_json,'$.status')='certified' ORDER BY id DESC LIMIT 1").fetchone()
    certificate = json.loads(row[0])
    expression = json.loads(certificate["arms"]["treatment"][0]["response"])["expression"]
    case = work / ("rc-" + uuid4().hex[:6]); case.mkdir()
    target = case / "config.json"; original = json.dumps({"expression":expression}).encode()
    target.write_bytes(original); initial_mtime = target.stat().st_mtime_ns
    loop = WorkerLoop(db_path=db, runs_dir=case / "r", lock_file=case / "lock", stop_file=case / "stop")
    task = loop.autonomous_tasks.enqueue("write_governed_text_artifact",
        {"target":str(target),"authorized_root":str(case),"content":json.dumps({"expression":"0","padding":"x"*4*1024**2}),"correlation_id":origin["correlation_id"]},
        idempotency_key=case.name, priority=0, max_attempts=3)
    started=time.monotonic(); observations=[]; crash={}; child_pids=set(); finished=threading.Event()
    def observe():
        target_child = None
        while not finished.wait(0.001):
            children=mp.active_children()
            if target_child is None and len(children)==1:
                with sqlite3.connect(db) as c:
                    state=c.execute("SELECT status,lease_generation,worker_id FROM autonomous_tasks WHERE task_id=?",(task["task_id"],)).fetchone()
                if state[0]=="running": target_child=children[0]
            if target.stat().st_mtime_ns != initial_mtime and not crash and target_child is not None and target_child.is_alive():
                crash.update(pid=target_child.pid,timestamp=utc_now(),lease_generation=state[1],worker_id=state[2],mtime_ns=target.stat().st_mtime_ns,at_seconds=time.monotonic()-started)
                target_child.kill(); target_child.join(timeout=5)
                crash['exit_code']=target_child.exitcode
            if crash:
                child_pids.update(child.pid for child in children if child.pid != crash["pid"])
                state=loop.autonomous_tasks.get(task["task_id"])
                if not observations or observations[-1]["status"] != state["status"]:
                    observations.append({"timestamp":utc_now(),"status":state["status"],"attempt":state["attempt"],"lease_generation":state["lease_generation"]})
                if state["status"] in {"completed","dead_letter","skipped","blocked"}:
                    loop.request_stop();return
            if time.monotonic()-started>180:
                loop.request_stop();return
    watcher=threading.Thread(target=observe,daemon=True);watcher.start()
    try:
        summary=loop.run(WorkerRunConfig(max_iterations=20,sleep_seconds=20,task_timeout=30,once=False,daemon=True,
            max_concurrent_tasks=1,runs_dir=str(case/"r"),lock_file=str(case/"lock"),stop_file=str(case/"stop")))
    finally:
        finished.set();watcher.join(timeout=10)
    final=loop.autonomous_tasks.get(task["task_id"])
    result=json.loads(Path(final["result_ref"]).read_text()) if final.get("result_ref") else {}
    replay = result.get("execution", {}).get("idempotent_replay")
    with sqlite3.connect(db) as c:integrity=c.execute("PRAGMA quick_check").fetchone()[0]
    same_mtime=bool(crash and target.stat().st_mtime_ns==crash["mtime_ns"])
    truth=bool(crash and crash.get('exit_code') not in (None,0) and final["status"]=="completed" and final["lease_generation"]>crash["lease_generation"] and replay and same_mtime and integrity=="ok")
    report={"timestamp":utc_now(),"tested_source_sha":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        "task_id":task["task_id"],"correlation_id":origin["correlation_id"],"crash":crash,"new_handler_pids":sorted(child_pids),
        "observations":observations,"final_status":final["status"],"lease_generation_after":final["lease_generation"],
        "recovery_seconds":round(time.monotonic()-started-crash.get("at_seconds",0),3),"duplicate_effects":0 if same_mtime and replay else None,
        "lost_tasks":int(final["status"]!="completed"),"db_integrity":integrity,"summary_errors":summary.get("errors"),"artifact_ref":str(case),
        "rollback_spec":json.loads(next((case/"r/effects").glob("*/rollback-spec.json")).read_text()),"baseline_sha256":hashlib.sha256(original).hexdigest(),
        "scope":"One normal WorkerLoop startup; GovernedTaskExecutor detects real owned child death and queue retry is automatic; no manual claim/recover/restart per stage", "truth":truth}
    destination=ROOT/"reports/evolution/normal_worker_recovery_latest.json"
    if destination.exists(): destination.with_name('normal_worker_recovery_attempt-'+uuid4().hex+'.json').write_bytes(destination.read_bytes())
    destination.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("truth","final_status","duplicate_effects","lost_tasks","recovery_seconds")}))

if __name__=="__main__": main()

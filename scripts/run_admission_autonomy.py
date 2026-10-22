import json
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TRIADE_ENTRYPOINT_KIND='manual_diagnostic'
from scripts.run_level8_soak import runtime_hash
from triade.core.contracts import utc_now
from triade.workers.contracts import WorkerRunConfig
from triade.workers.worker_loop import WorkerLoop


def main():
 prior=json.loads((ROOT/'reports/evolution/productive_learning_chain_v3.json').read_text(encoding='utf-8'))
 work=Path(prior['artifact_ref']).resolve()
 if not work.is_relative_to(ROOT/'artifacts/evolution'):raise ValueError('scope')
 db=work/'learning.db';cid=prior['candidate_id'];start=time.monotonic();observations=[]
 sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 fingerprint=runtime_hash()
 source_dirty=bool(subprocess.check_output(['git','status','--porcelain','--','triade','scripts','tests'],cwd=ROOT,text=True).strip())
 loop=WorkerLoop(db_path=db,runs_dir=work/'r',lock_file=work/'automatic.lock',stop_file=work/'automatic.stop')
 loop.clear_stop()
 finished=threading.Event()
 def observe():
  while not finished.wait(10):
   with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as conn:
    candidate=conn.execute('select status,run_use_count from learning_queue where candidate_id=?',(cid,)).fetchone()
    tasks=dict(conn.execute('select status,count(*) from autonomous_tasks group by status').fetchall())
    events=conn.execute('select max(id) from neuron_education_events').fetchone()[0]
    earned=conn.execute("select count(*) from neuron_learning_assignments where candidate_id=? and status='beneficial' and use_count>=5",(cid,)).fetchone()[0]
   observations.append({'timestamp':utc_now(),'candidate':list(candidate),'tasks':tasks,'education_event_max_id':events})
   if (candidate[0]=='consolidated' and earned>0) or time.monotonic()-start>600:
    loop.request_stop();return
 watcher=threading.Thread(target=observe,daemon=True);watcher.start()
 try:
  result=loop.run(WorkerRunConfig(max_iterations=40,sleep_seconds=20,task_timeout=120,once=False,daemon=True,concurrency_enabled=True,max_tasks_per_drain=20,max_seconds_per_drain=2,runs_dir=str(work/'r'),lock_file=str(work/'automatic.lock'),stop_file=str(work/'automatic.stop')))
 finally:finished.set();watcher.join(timeout=15)
 output={'timestamp':utc_now(),'tested_source_sha':sha,'source_unchanged':sha==subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'correlation_id':prior['correlation_id'],'candidate_id':cid,'artifact_ref':str(work),'duration_seconds':time.monotonic()-start,'observations':observations,'worker_summary':result,'human_prompts_during_window':0,'scope':'one normal WorkerLoop startup in existing independently observed experiment; no manual task dispatch during window'}
 with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as connection:
  output['candidate_after']=list(connection.execute('select status,run_use_count from learning_queue where candidate_id=?',(cid,)).fetchone())
  output['beneficial_assignments']=connection.execute("select count(*) from neuron_learning_assignments where candidate_id=? and status='beneficial' and use_count>=5",(cid,)).fetchone()[0]
 output['source_unchanged']=output['source_unchanged'] and fingerprint==runtime_hash() and not source_dirty
 output['source_dirty_at_start']=source_dirty
 output['truth']=output['source_unchanged'] and output['candidate_after'][0]=='consolidated' and output['beneficial_assignments']>0 and result.get('iterations',0)>1
 (ROOT/'reports/evolution/autonomous_admission_observation.json').write_text(json.dumps(output,indent=2,default=str),encoding='utf-8')
 print(json.dumps({'status':result.get('status'),'iterations':result.get('iterations'),'duration_seconds':output['duration_seconds']}))
if __name__=='__main__':main()

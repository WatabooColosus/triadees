#!/usr/bin/env python3
"""Gate de aceptación: exige dos lecturas con progreso real."""
from __future__ import annotations
import argparse,json,subprocess,sys,time
from pathlib import Path

def snap(script,root):
 p=subprocess.run([sys.executable,str(script),"--root",str(root)],capture_output=True,text=True,check=True)
 return json.loads(p.stdout[:p.stdout.rfind('}')+1])

a=argparse.ArgumentParser();a.add_argument('--root',default='/content/Triade');a.add_argument('--wait',type=int,default=30);a.add_argument('--script',default='upgrade_triade_580.py');x=a.parse_args()
a1=snap(x.script,x.root);time.sleep(x.wait);a2=snap(x.script,x.root)
checks={
 'sqlite_ok':a2['checks'].get('sqlite_integrity')=='ok',
 'heartbeat_fresh':a2.get('latest_health',{}).get('metrics',{}).get('heartbeat_age_seconds',999)<30,
 'worker_iterations_positive':json.loads(a2.get('latest_worker',{}).get('summary_json','{}') or '{}').get('iterations',0)>0,
 'health_not_stalled':a2.get('latest_health',{}).get('state')!='stalled',
 'transition_changed':a1.get('latest_health',{}).get('metrics',{}).get('last_task_transition_at') != a2.get('latest_health',{}).get('metrics',{}).get('last_task_transition_at'),
}
print(json.dumps({'version':'5.8.0','checks':checks,'pass':all(checks.values()),'before':a1.get('latest_health'),'after':a2.get('latest_health')},ensure_ascii=False,indent=2)); raise SystemExit(0 if all(checks.values()) else 1)

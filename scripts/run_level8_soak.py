"""Read-only, wall-clock observation of the normal localhost runtime."""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from scripts.run_long_validation import muestra

ROOT = Path(__file__).resolve().parents[1]

def runtime_hash():
    h = hashlib.sha256()
    for folder in ('triade', 'apps'):
        for p in sorted((ROOT / folder).rglob('*.py')):
            h.update(str(p.relative_to(ROOT)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()

def bind_report(report):
    report['runtime_source_hash']=runtime_hash()
    report['harness_hashes']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('scripts/run_level8_soak.py','scripts/run_long_validation.py','scripts/run_level8_learning_transfer.py','scripts/run_level8_task_recovery.py','scripts/run_level8_clean_restart.py','scripts/run_level8_api_recovery.py')}
    return report

def summarize(samples, duration, unchanged):
    rss = [s['process'].get('rss_kb', 0) / 1024 for s in samples if s.get('process', {}).get('alive')]
    healthy = bool(samples) and all(s.get('process', {}).get('alive') and s.get('supervision', {}).get('url_available') and s.get('integrity_check') == 'ok' for s in samples)
    first, last = samples[0], samples[-1]
    delta = lambda k: last.get(k, 0) - first.get(k, 0)
    task_delta = lambda k: last.get('tasks_by_status', {}).get(k, 0) - first.get('tasks_by_status', {}).get(k, 0)
    growth = rss[-1] - rss[0] if rss else None
    trend = len(rss) >= 10 and all(b > a + 1 for a,b in zip(rss[-6:],rss[-5:]))
    return {'duration_seconds':duration, 'samples':len(samples), 'cycles':delta('metabolic_cycles'),
        'tasks_completed':task_delta('completed'), 'tasks_failed':task_delta('dead_letter'),
        'learning_events':delta('learning_events'), 'memory_growth_bytes':delta('db_bytes'),
        'human_interventions':0, 'rss_start_mb':rss[0] if rss else None,
        'rss_end_mb':rss[-1] if rss else None, 'rss_peak_mb':max(rss) if rss else None,
        'growth_mb':growth, 'growth_percent':100*growth/rss[0] if rss and rss[0] else None,
        'memory_classification':'INSUFFICIENT_EVIDENCE' if len(rss)<10 else 'POSSIBLE_LEAK' if trend else 'STABLE',
        'runtime_source_unchanged':unchanged, 'healthy':healthy,
        'truth':healthy and unchanged and duration >= 1800 and delta('metabolic_cycles')>0 and task_delta('completed')>0,
        'scope':'Continuous operational activity; no claim of autonomous educational improvement',
        '24h':'NOT_YET_PROVEN','72h':'NOT_YET_PROVEN'}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--seconds',type=float,default=1800)
    ap.add_argument('--interval',type=float,default=60)
    ap.add_argument('--output',type=Path,default=ROOT/'reports/level8/background_autonomy_v2.json')
    args=ap.parse_args()
    stamp=datetime.now(UTC).isoformat()
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    fingerprint=runtime_hash()
    evidence=ROOT/'artifacts/level8/closure-soak.jsonl'
    evidence.parent.mkdir(parents=True,exist_ok=True)
    samples=[]
    start=time.monotonic()
    with evidence.open('w',encoding='utf-8') as out:
        while True:
            sample=muestra()
            samples.append(sample)
            out.write(json.dumps(sample)+'\n');out.flush()
            elapsed=time.monotonic()-start
            if elapsed>=args.seconds:break
            time.sleep(min(args.interval,args.seconds-elapsed))
    report={'git_sha':sha,'timestamp':stamp,'runtime_source_hash':fingerprint,
        **summarize(samples,time.monotonic()-start,runtime_hash()==fingerprint),
        'observations':samples,'evidence_ref':str(evidence.relative_to(ROOT))}
    bind_report(report)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='observations'}))
    return 0 if report['truth'] else 1

if __name__=='__main__':raise SystemExit(main())

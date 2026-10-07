"""Run the bounded tool-assisted transfer experiment; preserve historical results."""
from __future__ import annotations
import json
import os
import time
from datetime import UTC, datetime
from scripts.run_level8_learning_transfer import ROOT, run
TRIADE_ENTRYPOINT_KIND = 'manual_diagnostic'


def main():
    # Scoped to this test process; normal runtime configuration is unchanged.
    os.environ['TRIADE_LOW_RESOURCE_MODE']='1'
    work=ROOT/'artifacts/evolution'/f'transfer-{time.time_ns()}'
    out=ROOT/'reports/evolution/learning_transfer_latest.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    if out.exists():
        prior=out.read_bytes()
        (out.parent/f'learning_transfer_attempt-{time.time_ns()}.json').write_bytes(prior)
    try:
        result=run(work,use_expression=True)
        result['scope']='Isolated normal learning pipeline and model client plus bounded arithmetic tool; NOT productive Central/education certification'
    except (RuntimeError, OSError, ValueError) as exc:
        result={'timestamp':datetime.now(UTC).isoformat(),'truth':False,'decision':'ABORT','reason':str(exc),'artifact_ref':str(work)}
    result['budget']={'max_runtime_seconds':300,'minimum_ram_available_mb':1536,'max_llm_task_calls':19,'max_tasks':0,'max_disk_write_mb':10}
    result['artifact_ref']=str(work)
    from scripts.run_level8_soak import bind_report
    bind_report(result)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result.get(k) for k in ['truth','metrics_before','metrics_after','metrics_control','reason']}))
    return 0 if result['truth'] else 1


if __name__=='__main__':
    raise SystemExit(main())

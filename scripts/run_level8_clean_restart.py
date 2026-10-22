"""Actual ASGI lifespan shutdown/restart in a repository-owned sandbox."""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def server(root,port,iteration):
    root=Path(root);os.chdir(root)
    os.environ.update(TRIADE_DB_PATH=str(root/'triade/memory/triade.db'),TRIADE_AUTH_DB_PATH=str(root/'triade/memory/triade.db'),TRIADE_RUNTIME_SCOPE='local',TRIADE_DISABLE_BACKGROUND='0',TRIADE_LOCAL_NO_AUTH='1',TRIADE_PUBLIC_GUARDED='true',TRIADE_TEST_ROOT=str(root),TRIADE_ALWAYS_ON='1',TRIADE_WORKERS_ALWAYS_ON='1',TRIADE_WORKERS_AUTOSTART='1',TRIADE_WORKER_MODE='light_background',TRIADE_ALWAYS_ON_MODE='light_background')
    os.environ.pop('PYTEST_CURRENT_TEST',None)
    # Never inherit the operator's backup key or key-location configuration.
    for name in ('TRIADE_BACKUP_KEY','TRIADE_BACKUP_KEY_FILE','TRIADE_AUTH_VAULT_KEY'):os.environ.pop(name,None)
    os.environ['TRIADE_BACKUP_KEY_FILE']=str(root/'sandbox-backup.key')
    key=(root/'sandbox-backup.key').read_text(encoding='utf-8').strip()
    os.environ['TRIADE_BACKUP_KEY']=key
    os.environ['TRIADE_AUTH_VAULT_KEY']=key
    from triade.core.bodega import Bodega
    Bodega(db_path=root/'triade/memory/triade.db')
    import uvicorn

    import apps.single_port_app as app
    original=app._stop_background
    def observe_stop(db_path):
        result=original(db_path)
        (root/f'shutdown-{iteration}.json').write_text(json.dumps(result,default=str,indent=2),encoding='utf-8')
        return result
    app._stop_background=observe_stop
    runner=uvicorn.Server(uvicorn.Config(app.app,host='127.0.0.1',port=port,log_level='warning'))
    def request_stop():
        while not (root/f'stop-{iteration}').exists():time.sleep(.2)
        runner.should_exit=True
    threading.Thread(target=request_stop,daemon=True).start()
    runner.run()
    from triade.core import worker_autostart
    worker_thread=worker_autostart._WORKER_THREAD
    if worker_thread is not None:worker_thread.join(timeout=20)
    final={'worker_thread_alive':bool(worker_thread and worker_thread.is_alive()),'worker_lock_file_active':(root/'runs/background/.triade_workers.lock').exists()}
    (root/f'final-stop-{iteration}.json').write_text(json.dumps(final),encoding='utf-8')

def run(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    from cryptography.fernet import Fernet

    from triade.security.file_privacy import protect_private_file
    key_path=root/'sandbox-backup.key'
    key_path.write_text(Fernet.generate_key().decode(),encoding='utf-8')
    if not protect_private_file(key_path):raise RuntimeError('sandbox key permissions not private')
    shutil.copyfile(ROOT/'triade.yml',root/'triade.yml')
    memory=root/'triade/memory';memory.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ROOT/'triade/memory/schemas.sql',memory/'schemas.sql')
    shutil.copytree(ROOT/'triade/memory/migrations',memory/'migrations')
    (root/'runs/background').mkdir(parents=True,exist_ok=True)
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    observations=[];processes=[]
    for i in (1,2):
        child=mp.Process(target=server,args=(str(root),port,i));child.start();processes.append(child)
        deadline=time.monotonic()+70;health=None
        try:
            while time.monotonic()<deadline and child.is_alive():
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health',timeout=2) as r:health=json.load(r)
                    break
                except (OSError,ValueError):time.sleep(.4)
            if not health:raise RuntimeError('sandbox API never became ready')
            db=root/'triade/memory/triade.db'
            with sqlite3.connect(db) as c:
                identity=c.execute('SELECT identity_core_hash,manifest_hash FROM identity_manifest_anchor').fetchall()
                integrity=c.execute('PRAGMA integrity_check').fetchone()[0]
            start=time.monotonic();(root/f'stop-{i}').write_text('graceful',encoding='utf-8')
            child.join(45)
            if child.is_alive():raise RuntimeError('graceful shutdown did not exit')
            stopped=json.loads((root/f'shutdown-{i}.json').read_text())
            with sqlite3.connect(db,timeout=2) as c:
                c.execute('BEGIN EXCLUSIVE');c.rollback()
            final=json.loads((root/f'final-stop-{i}.json').read_text())
            observations.append({'pid':child.pid,'exit_code':child.exitcode,'identity':identity,'integrity':integrity,'shutdown_seconds':time.monotonic()-start,'background_stop':stopped,'final_background_state':final,'db_lock_reacquired':True})
        finally:
            if child.is_alive():child.terminate();child.join()
    truth=all(x['exit_code']==0 and x['integrity']=='ok' and x['db_lock_reacquired'] and not any(x['final_background_state'].values()) and not any(v.get('status')=='error' for v in x['background_stop'].values()) for x in observations) and observations[0]['identity']==observations[1]['identity'] and bool(observations[0]['identity'])
    return {'git_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'timestamp':datetime.now(UTC).isoformat(),'truth':truth,'scope':'Actual isolated API lifespan restart and nonempty identity persistence; not production in-flight clean shutdown certification','observations':observations,'production_writes':False}

def main():
    result=run(ROOT/'artifacts/level8'/f'clean-restart-{time.time_ns()}')
    from scripts.run_level8_soak import bind_report
    bind_report(result)
    (ROOT/'reports/level8/clean_restart_v2.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'truth':result['truth'],'observations':[{k:x[k] for k in ['pid','exit_code','shutdown_seconds','final_background_state']} for x in result['observations']]}))
    return 0 if result['truth'] else 1

if __name__=='__main__':raise SystemExit(main())

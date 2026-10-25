"""Colab R5/R6.2 -> R6.3 guarded, pinned source update.

API restart is explicit, authenticated service ownership is required.
Never writes to Google Drive, canonical snapshots, identity or SQLite live tables.
"""
from __future__ import annotations
import ast
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.request

VERSION = 'R6.3-rc'
COMMIT = '777dd370dd8b23f5d93303afa7796ceba51166ba'
R5_HEAD = '8fdd397b09d7c7da5da8db30235ce626d6a271ec'
R62_COMMIT = '860351246340913c5095ab85e7087facadb5a21f'
REPO_ORIGIN = 'https://github.com/WatabooColosus/triadees.git'
FILES = (
    'triade/neurons/functional_evidence.py',
    'triade/neurons/education_resolver.py',
    'tools/triade_r63_probe.py',
)
TEST = 'tests/test_neuron_functional_evidence.py'
NEW_FILES = {'triade/neurons/functional_evidence.py','tools/triade_r63_probe.py'}
MAX_SOURCE = 450_000


def _digest(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _cmd(args, *, cwd=None, timeout=75, env=None):
    p=subprocess.run(args,cwd=cwd,timeout=timeout,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
    if p.returncode:
        raise RuntimeError(f'Error verificando {args[0]} ({p.returncode}): '+p.stderr.decode(errors='replace')[-700:])
    return p.stdout


def _json(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    os.chmod(tmp,0o600)
    os.replace(tmp,path)


def _runtime(r5):
    root=Path(r5.ROOT).resolve()
    work=Path(r5.WORK).resolve()
    db=Path(r5.DB).resolve()
    if not (root/'.git').is_dir() or not db.is_file() or not (root/'frontend/dist/index.html').is_file():
        raise RuntimeError('R5 no está instalado/conectado')
    sha=_cmd(['git','-C',str(root),'rev-parse','HEAD']).decode().strip()
    if sha!=R5_HEAD:raise RuntimeError('HEAD distinto del R5 autorizado: '+sha[:12])
    origin=_cmd(['git','-C',str(root),'remote','get-url','origin']).decode().strip()
    if origin not in (REPO_ORIGIN,REPO_ORIGIN.removesuffix('.git')):
        raise RuntimeError('El repositorio origin no coincide con Tríade')
    for fn in ('restore_proof.json','r5_continuity.json'):
        if not (work/fn).is_file():raise RuntimeError('Falta prueba de continuidad '+fn)
    active = work/'actualizaciones'/'r62_active.json'
    if not active.is_file() or json.loads(active.read_text(encoding='utf8')).get('candidate_commit') != R62_COMMIT:
        raise RuntimeError('R6.2 operativa no acreditada; no aplicar R6.3')
    # R6.2 used live source modifications on top of the pinned R5 HEAD.
    for rel in ('triade/core/runner.py','triade/core/verified_run_mission_bridge.py',
                'triade/workers/mission_planner.py','triade/workers/worker_loop.py'):
        expected = _cmd(['git','-C',str(root),'show',f'{R62_COMMIT}:{rel}'],timeout=30)
        actual = root/rel
        if not actual.is_file() or actual.read_bytes()!=expected:
            raise RuntimeError('Código R6.2 no coincide con base certificada: '+rel)
    r5._owner_account_status(db)
    r5.check_working_identity()
    with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=25) as conn:
        if conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':
            raise RuntimeError('Bodega sin integridad')
        counts={x:conn.execute(f'SELECT COUNT(*) FROM {x}').fetchone()[0] for x in ('neurons','autonomous_tasks','auth_users')}
    return root,work,db,counts


def _path(root, relative):
    p=root/relative
    if not p.resolve().is_relative_to(root):raise RuntimeError('Ruta fuera del proyecto')
    if p.is_symlink() or any(x.is_symlink() for x in [p.parent,p.parent.parent]):
        raise RuntimeError('Ruta de código con enlace simbólico')
    return p


def _stage_dir(work):
    return work/'actualizaciones'/'r63_verified'


def prepare(r5):
    """Fetch a *fixed commit* to FETCH_HEAD; stage source and test, no writes to API code."""
    root,work,db,counts=_runtime(r5)
    _cmd(['git','-C',str(root),'fetch','--no-tags','--depth','1','origin',COMMIT],timeout=160)
    fetched=_cmd(['git','-C',str(root),'rev-parse','FETCH_HEAD']).decode().strip()
    if fetched!=COMMIT:raise RuntimeError('Git devolvió otro commit')
    stage=_stage_dir(work);stage.mkdir(parents=True,exist_ok=True)
    os.chmod(stage,0o700)
    hashes={}
    changes=[]
    for rel in (*FILES,TEST):
        src=_cmd(['git','-C',str(root),'show',f'{COMMIT}:{rel}'],timeout=30)
        if not src or len(src)>MAX_SOURCE:raise RuntimeError('Módulo fuera de los límites: '+rel)
        ast.parse(src.decode('utf8'),filename=rel)
        dest=_path(stage,rel)
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists() and dest.read_bytes()!=src:raise RuntimeError('Stage existente en conflicto: '+rel)
        if not dest.exists():
            fd=os.open(str(dest),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as out:out.write(src)
        hashes[rel]=_digest(src)
        if rel in FILES:
            live=_path(root,rel)
            base=None if rel in NEW_FILES else _cmd(['git','-C',str(root),'show',f'{R62_COMMIT}:{rel}'],timeout=30)
            current=live.read_bytes() if live.is_file() else None
            if current is not None and current!=src and current!=base:
                raise RuntimeError('Cambios locales en '+rel+'. No sobrescribir sin revisar.')
            if current is None and base is not None:
                raise RuntimeError('Falta un módulo original: '+rel)
            changes.append({'file':rel,'state':'already_candidate' if current==src else 'needs_update'})
    # Run isolated tests with module import rooted in stage. Do not import app or mutate production DB.
    env={**os.environ,'PYTHONPATH':str((stage/'triade/neurons').resolve())}
    test_result=_cmd([sys.executable,'-m','unittest','discover','-s',str(stage/'tests'),'-p','test_neuron_functional_evidence.py','-v'],cwd=stage,env=env,timeout=65)
    meta={'status':'staged_verified','version':VERSION,'candidate_commit':COMMIT,'base_sha':R5_HEAD,
          'source_hashes':hashes,'changes':changes,'sqlite_integrity':'ok','counts':counts,
          'tests':'pass','tests_detail':test_result.decode(errors='replace')[-700:],
          'prepared_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    _json(stage/'stage.json',meta)
    return meta


def _verify_stage(r5):
    root,work,db,counts=_runtime(r5)
    stage=_stage_dir(work)
    m=json.loads((stage/'stage.json').read_text(encoding='utf8'))
    if m.get('status')!='staged_verified' or m.get('candidate_commit')!=COMMIT:
        raise RuntimeError('R6.3 todavía no preparada y verificada')
    if any(counts.get(k,0)<v for k,v in m.get('counts',{}).items()):
        raise RuntimeError('Regresión de conteos respecto al staging')
    for rel,h in m['source_hashes'].items():
        if _digest(_path(stage,rel).read_bytes())!=h:
            raise RuntimeError('Stage modificado: '+rel)
    for rel in FILES:
        current=_path(root,rel)
        staged=_path(stage,rel).read_bytes()
        if current.is_file() and current.read_bytes()==staged:continue
        if rel in NEW_FILES and not current.exists():continue
        base=_cmd(['git','-C',str(root),'show',f'{R62_COMMIT}:{rel}'])
        if not current.is_file() or current.read_bytes()!=base:raise RuntimeError('Conflicto de versión: '+rel)
    return root,work,db,stage,counts


def _savedb(src,dest):
    # Consistent SQLite online backup, independent of active WAL.
    with sqlite3.connect(src.as_uri()+'?mode=ro',uri=True,timeout=40) as inp:
        with sqlite3.connect(dest,timeout=40) as out:
            inp.backup(out,pages=128,sleep=0.1)
    with sqlite3.connect(dest) as conn:
        if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise RuntimeError('Copia de Bodega no superó comprobación de integridad')
    os.chmod(dest,0o600)


def _stop_r5_owned(r5, root, work):
    import psutil
    from tools.colab_service_lifecycle import process_owned
    record=work/'api_ownership.json'
    if not process_owned(root,record,port=8010):
        raise RuntimeError('API no acreditada como propia. No se detiene ningún servicio.')
    details=json.loads(record.read_text(encoding='utf8'))
    proc=psutil.Process(int(details['pid']))
    if abs(proc.create_time()-float(details['create_time']))>1:
        raise RuntimeError('PID reutilizado, parada bloqueada')
    proc.send_signal(signal.SIGTERM)
    # psutil.Process.wait() can hang on non-child Colab subprocesses; poll PID + listener instead.
    for _ in range(100):
        is_alive=False
        try:
            p=psutil.Process(int(details['pid']))
            is_alive=(abs(p.create_time()-float(details['create_time']))<=1 and p.status()!=psutil.STATUS_ZOMBIE)
        except psutil.NoSuchProcess:pass
        listeners=[c for c in psutil.net_connections(kind='inet') if c.status=='LISTEN' and c.laddr and c.laddr.port==8010]
        if not is_alive and not listeners:
            record.unlink(missing_ok=True)
            (work/'r5_backend.json').unlink(missing_ok=True)
            return
        time.sleep(0.5)
    raise RuntimeError('API no terminó con SIGTERM; NO se modificó código, no se usa SIGKILL.')


def apply_and_restart(r5, authorization):
    if authorization.strip()!='ACTUALIZAR R6.3':
        raise RuntimeError('Escribe ACTUALIZAR R6.3 exactamente')
    root,work,db,stage,counts=_verify_stage(r5)
    if all(_path(root,rel).is_file() and _path(root,rel).read_bytes()==_path(stage,rel).read_bytes() for rel in FILES):
        return {'status':'already_installed','version':VERSION,'no_restart':True}
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=work/'actualizaciones'/'r63_backup'/stamp
    backup.mkdir(parents=True,exist_ok=False)
    os.chmod(backup,0o700)
    _savedb(db,backup/'pre_update.sqlite3')
    for rel in FILES:
        old=_path(root,rel)
        if old.exists():
            dest=backup/rel;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(old,dest)
    _json(backup/'before.json',{'version':VERSION,'backup_created_at':stamp,'db_snapshot':'pre_update.sqlite3',
                                'code_files':list(FILES),'counts':counts,'commit':COMMIT})
    print('✓ Respaldo SQLite consistente e íntegro. Intentando detener únicamente API R5...')
    sys.path.insert(0,str(root))
    _stop_r5_owned(r5,root,work)
    print('✓ API propia detenida; Ollama y Drive no se tocaron.')
    installed=[]
    try:
        for rel in FILES:
            dest=_path(root,rel)
            src=_path(stage,rel).read_bytes()
            dest.parent.mkdir(parents=True,exist_ok=True)
            tmp=dest.with_name('.'+dest.name+'.r63tmp')
            if tmp.exists():raise RuntimeError('Existe archivo temporal ajeno: '+str(tmp))
            fd=os.open(str(tmp),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as out:
                out.write(src);out.flush();os.fsync(out.fileno())
            os.replace(tmp,dest)
            installed.append(rel)
        for rel in FILES:
            if _digest(_path(root,rel).read_bytes())!=_digest(_path(stage,rel).read_bytes()):
                raise RuntimeError('Integridad de instalación falló para '+rel)
        print('✓ Código R6.3 aplicado. Iniciando backend protegido...')
        r5.start_real_backend()
        with urllib.request.urlopen('http://127.0.0.1:8010/health/live',timeout=15) as response:
            if response.status!=200:raise RuntimeError('R6.3 sin HTTP 200')
    except Exception as exc:
        # Roll back code only if API is no longer listening, to avoid mixing versions.
        import psutil
        listening=any(c.status=='LISTEN' and c.laddr and c.laddr.port==8010 for c in psutil.net_connections(kind='inet'))
        if not listening:
            for rel in installed:
                restore=backup/rel
                target=_path(root,rel)
                if restore.is_file():shutil.copy2(restore,target)
                elif target.exists():target.unlink()
            print('✗ Código original restaurado. Intentando levantar R5 anterior...')
            try:r5.start_real_backend()
            except Exception as rollback_exc:
                print('✗ No se pudo iniciar R5 anterior:',type(rollback_exc).__name__,str(rollback_exc)[:280])
        raise RuntimeError('R6.3 no certificada; revisar API y archivos preservados. '+str(exc)) from exc
    out={'status':'active_candidate','version':VERSION,'candidate_commit':COMMIT,
         'git_head_unmodified':R5_HEAD,'r62_base':R62_COMMIT,'database_restored':False,'database_replaced':False,
         'identity_untouched':True,'api_http':200,'backup':str(backup),
         'verified_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    _json(work/'actualizaciones'/'r63_active.json',out)
    return out


def render_panel(r5):
    import ipywidgets as widgets
    from IPython.display import display,clear_output
    header=widgets.HTML('<div style="background:#0d214b;color:white;padding:16px;border-radius:14px"><b>TRÍADE Ω · R6.3 Git</b><p>Verifica código y pruebas antes de autorizar. Solo se reinicia la API propia cuando tú lo indicas.</p></div>')
    prepare_button=widgets.Button(description='1. Preparar y probar R6.3',button_style='info')
    install_button=widgets.Button(description='2. Instalar y reiniciar API propia',button_style='warning',disabled=True)
    approval=widgets.Text(placeholder='Escribe ACTUALIZAR R6.3',layout=widgets.Layout(width='95%'))
    out=widgets.Output(layout=widgets.Layout(max_height='400px',overflow='auto',border='1px solid #395273'))
    state={'prepared':False}
    def prepare_click(_):
        with out:
            clear_output(wait=True)
            try:
                r=prepare(r5)
                state['prepared']=True;install_button.disabled=False
                print('✓ Commit:',r['candidate_commit'])
                print('✓ Pruebas:',r['tests'])
                print('✓ Integridad DB:',r['sqlite_integrity'])
                print('✓ Archivos:',r['changes'])
                print('AÚN NO se modificó backend ni se reiniciaron servicios')
            except Exception as exc:
                state['prepared']=False;install_button.disabled=True
                print('✗',type(exc).__name__,str(exc))
    def install_click(_):
        with out:
            clear_output(wait=True)
            try:
                if not state['prepared']:raise RuntimeError('Primero preparar y probar')
                x=apply_and_restart(r5,approval.value)
                print('✓ Resultado:',json.dumps(x,ensure_ascii=False,indent=2))
                approval.value='';install_button.disabled=True
            except Exception as exc:
                print('✗',type(exc).__name__,str(exc))
    prepare_button.on_click(prepare_click)
    install_button.on_click(install_click)
    display(widgets.VBox([header,prepare_button,approval,install_button,out]))
    return state
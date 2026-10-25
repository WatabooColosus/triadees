"""R5 update center: stage a known R6 operational patch from ZIP/Drive/Git.

This does NOT update the core git checkout, release manifest, or Colab services.
The patch affects only mission links after explicit confirmation and guarded backup.
"""
from __future__ import annotations
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile, BadZipFile

VERSION = 'R6.0'
PATCH_NAME = 'triade_integral_r6.py'
PATCH_SHA256 = '229402baf14927e36a5041a995f7c1e7340988710ec0e92532f51edf49377599'
BASE_SHA = '8fdd397b09d7c7da5da8db30235ce626d6a271ec'
# Set by release publisher, pinned to the exact commit, never a moving main branch.
GIT_REF = 'd6c5db5ab405e70f2123345c9c406acc9f88252e'
GIT_URL = f'https://raw.githubusercontent.com/WatabooColosus/triadees/{GIT_REF}/tools/triade_integral_r6.py'
BASE = Path('/content/triade_operacion_r5/actualizaciones')
DRIVE_BASE = Path('/content/drive/MyDrive/Triade')
MAX_ARCHIVE = 2_000_000


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _checked_source(content: bytes) -> bytes:
    if len(content) > MAX_ARCHIVE: raise RuntimeError('Actualización demasiado grande')
    if sha256(content) != PATCH_SHA256:
        raise RuntimeError('SHA256 no coincide con el R6 autorizado. Actualización rechazada.')
    ast.parse(content.decode('utf-8'), filename=PATCH_NAME)
    return content


def _extract_zip(contents: bytes) -> bytes:
    if len(contents) > MAX_ARCHIVE: raise RuntimeError('ZIP demasiado grande')
    from io import BytesIO
    try:
        with ZipFile(BytesIO(contents)) as archive:
            members = [x for x in archive.infolist() if not x.is_dir() and x.filename == PATCH_NAME]
            if len(members) != 1: raise RuntimeError('El paquete debe tener una sola copia de '+PATCH_NAME)
            if members[0].file_size > MAX_ARCHIVE: raise RuntimeError('Miembro R6 demasiado grande')
            source = archive.read(members[0])
            m = [x for x in archive.infolist() if x.filename=='manifest_update.json']
            if m:
                if len(m)!=1: raise RuntimeError('Manifiestos duplicados')
                manifest=json.loads(archive.read(m[0]))
                if manifest.get('patch_sha256')!=PATCH_SHA256 or manifest.get('version')!=VERSION or manifest.get('base_sha')!=BASE_SHA:
                    raise RuntimeError('Manifiesto de actualización no autorizado')
    except BadZipFile as exc:
        raise RuntimeError('El archivo no es un ZIP válido') from exc
    return _checked_source(source)


def stage_from_bytes(content: bytes, *, filename: str='paquete.zip', source: str='uploaded') -> dict:
    if not filename.lower().endswith('.zip'): raise RuntimeError('Solo paquetes ZIP autorizados')
    code=_extract_zip(content)
    BASE.mkdir(parents=True,exist_ok=True)
    os.chmod(BASE,0o700)
    dest=BASE/f'{PATCH_NAME[:-3]}_{PATCH_SHA256[:12]}.py'
    if dest.is_symlink(): raise RuntimeError('Archivo de destino inseguro')
    if dest.exists() and sha256(dest.read_bytes())!=PATCH_SHA256:
        raise RuntimeError('Conflicto en carpeta local; no sobrescribir')
    if not dest.exists():
        fd=os.open(dest,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        try:
            os.write(fd,code);os.fsync(fd)
        finally:os.close(fd)
    return {'version':VERSION,'source':source,'path':str(dest),'sha256':PATCH_SHA256,'staged':True,'applied':False}


def stage_from_file(path: str|Path, *, drive_only=False) -> dict:
    f=Path(path).expanduser().resolve(strict=True)
    if drive_only and not f.is_relative_to(DRIVE_BASE.resolve()):
        raise RuntimeError('Elegir un ZIP dentro de MyDrive/Triade')
    if not f.is_file() or f.stat().st_size>MAX_ARCHIVE:
        raise RuntimeError('No se encontró un ZIP de tamaño válido')
    return stage_from_bytes(f.read_bytes(),filename=f.name,source='drive' if drive_only else 'local')


def find_drive_candidates():
    if not DRIVE_BASE.is_dir():return []
    candidates=[]
    roots=[DRIVE_BASE/'actualizaciones',DRIVE_BASE/'distribucion',DRIVE_BASE]
    for root in roots:
        if root.is_dir():
            for f in root.glob('*R6*.zip'):
                if f.is_file() and f.stat().st_size <= MAX_ARCHIVE and f not in candidates:
                    candidates.append(f)
    return [str(f) for f in candidates[:25]]


def stage_from_git() -> dict:
    if not GIT_REF or GIT_REF.startswith('__'):raise RuntimeError('Git todavía no tiene release pinneada')
    with urlopen(GIT_URL,timeout=25) as response:
        code=response.read(MAX_ARCHIVE+1)
    # GitHub puede servir el archivo sin el LF final presente en el ZIP.
    # Solo se normaliza si el SHA del contenido resultante coincide EXACTAMENTE
    # con el SHA fijado; no se acepta codigo distinto.
    if sha256(code) != PATCH_SHA256 and sha256(code + b'\n') == PATCH_SHA256:
        code += b'\n'
    _checked_source(code)
    BASE.mkdir(parents=True,exist_ok=True)
    dest=BASE/f'{PATCH_NAME[:-3]}_{PATCH_SHA256[:12]}.py'
    if dest.is_symlink():raise RuntimeError('Ruta de script insegura')
    if dest.exists() and sha256(dest.read_bytes())!=PATCH_SHA256:
        raise RuntimeError('Conflicto en script local')
    if not dest.exists():
        fd=os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:os.write(fd,code);os.fsync(fd)
        finally:os.close(fd)
    return {'version':VERSION,'source':'git_pinned','git_commit':GIT_REF,'path':str(dest),'sha256':PATCH_SHA256,'staged':True,'applied':False}


def preflight(r5_module, script_path: str|Path) -> dict:
    path=Path(script_path).resolve(strict=True)
    if path.parent!=BASE.resolve() or sha256(path.read_bytes())!=PATCH_SHA256:
        raise RuntimeError('Script no verificado en el área controlada')
    if not r5_module._is_installed(): raise RuntimeError('R5 no verificado: no aplicar sobre otro checkout')
    if not r5_module.DB.is_file():raise RuntimeError('No hay Bodega instalada')
    for filename in ('restore_proof.json','r5_continuity.json'):
        if not (r5_module.WORK/filename).is_file():raise RuntimeError('Sin '+filename+'; continuidad no confirmada')
    r5_module._owner_account_status(r5_module.DB)
    r5_module.check_working_identity()
    with sqlite3.connect(r5_module.DB.resolve().as_uri()+'?mode=ro',uri=True) as c:
        integrity=c.execute('PRAGMA quick_check').fetchone()[0]
    if integrity!='ok':raise RuntimeError('La DB no supera PRAGMA quick_check')
    return {'code_sha':BASE_SHA,'database_integrity':integrity,'owner_ok':True,'identity_ok':True,
            'patch_sha256':PATCH_SHA256,'no_restart':True}


def execute(r5_module, script_path: str|Path, *, apply:bool=False, allow_drive_report=False):
    checks=preflight(r5_module,script_path)
    script=Path(script_path).resolve()
    output=BASE/'reportes'
    argv=[sys.executable,'-u',str(script),'repair' if apply else 'audit',
        '--root',str(r5_module.ROOT),'--db',str(r5_module.DB),'--out',str(output)]
    process=subprocess.run(argv, cwd=r5_module.ROOT,capture_output=True,text=True,timeout=210)
    if process.stdout:print(process.stdout[-8500:])
    if process.returncode:
        print(process.stderr[-3000:])
        raise RuntimeError('El módulo R6 falló sin aprobación de nueva actualización')
    result={'checks':checks,'mode':'repair' if apply else 'audit',
            'report':str(output/'report.json'),'returncode':process.returncode}
    if allow_drive_report and DRIVE_BASE.is_dir():
        # Only public counts and status, never keys/tokens or DB contents.
        report=json.loads((output/'report.json').read_text())
        redacted={'version':VERSION,'mode':result['mode'],
                  'mission_actions':report.get('before',{}).get('neuron_actions',{}),
                  'repair_status':report.get('repair',{}).get('status'),
                  'created_count':report.get('repair',{}).get('created_count',0)}
        dest=DRIVE_BASE/'operacion_colab_r5'/'auditorias';dest.mkdir(parents=True,exist_ok=True)
        (dest/'r6_update_public_report.json').write_text(json.dumps(redacted,indent=2))
    return result


def render_r5_update_area(ns: dict):
    import ipywidgets as w
    from IPython.display import display,clear_output
    r5=ns.get('r5')
    if r5 is None:raise RuntimeError('Ejecutar primero las celdas R5 de materialización y panel')
    header=w.HTML('<div style="background:#0e2149;color:#dcecff;padding:18px;border-radius:15px"><h3 style="margin:0">TRÍADE Ω · Centro de actualizaciones</h3><p>Actualizar desde ZIP, Google Drive o Git verificado. Nunca sustituye Bodega o identidad ni reinicia R5 automáticamente.</p></div>')
    picker=w.FileUpload(accept='.zip',multiple=False,description='Subir ZIP R6')
    drive_path=w.Text(value=str(DRIVE_BASE/'actualizaciones'/'TRIADE_OMEGA_ACTUALIZACION_OPERATIVA_R6.zip'),description='Drive ZIP',layout=w.Layout(width='96%'))
    git=w.Button(description='Buscar R6 en Git',button_style='info')
    from_drive=w.Button(description='Cargar desde Drive',button_style='info')
    inspect=w.Button(description='Auditar sin cambios',button_style='')
    apply=w.Button(description='Aplicar corrección segura',button_style='warning',disabled=True)
    approval=w.Text(value='',placeholder='Escribe APLICAR R6 para autorizar',layout=w.Layout(width='96%'))
    output=w.Output(layout=w.Layout(max_height='410px',overflow='auto',border='1px solid #405776',padding='9px'))
    state={'staged':None,'audited':False}
    def stage(result):
        state['staged']=result;state['audited']=False;apply.disabled=True
        print('✓ Paquete verificado y preparado:', result['version'],result['source'])
        print('SHA256:',result['sha256']);print('Todavía no se modificó Tríade')
    def uploaded(change):
        if not picker.value:return
        with output:
            clear_output(wait=True)
            try:
                v=picker.value
                item=list(v.values())[0] if isinstance(v,dict) else v[0]
                content=item['content'] if isinstance(item,dict) else item.content
                name=item.get('name','uploaded.zip') if isinstance(item,dict) else item.name
                stage(stage_from_bytes(bytes(content),filename=name,source='upload'))
            except Exception as ex:print('✗:',type(ex).__name__,str(ex))
    picker.observe(uploaded,names='value')
    def load_drive(_):
        with output:
            clear_output(wait=True)
            try:
                f=Path(drive_path.value)
                if not f.is_file():
                    options=find_drive_candidates()
                    print('No se encontró el archivo indicado. Archivos R6 en Drive:',*options,sep='\n')
                    return
                stage(stage_from_file(f,drive_only=True))
            except Exception as ex:print('✗:',type(ex).__name__,str(ex))
    from_drive.on_click(load_drive)
    def load_git(_):
        with output:
            clear_output(wait=True)
            try:stage(stage_from_git())
            except Exception as ex:print('✗:',type(ex).__name__,str(ex))
    git.on_click(load_git)
    def on_audit(_):
        with output:
            clear_output(wait=True)
            try:
                if state['staged'] is None:raise RuntimeError('Primero subir, localizar en Drive o cargar desde Git')
                r=execute(r5,state['staged']['path'],apply=False)
                state['audited']=True;apply.disabled=False
                print('✓ R6 auditado, sin modificaciones. Informe:',r['report'])
            except Exception as ex:print('✗:',type(ex).__name__,str(ex))
    inspect.on_click(on_audit)
    def on_apply(_):
        with output:
            clear_output(wait=True)
            try:
                if not state['audited']:raise RuntimeError('Auditar primero')
                if approval.value.strip()!='APLICAR R6':raise RuntimeError('Escribe APLICAR R6 exactamente')
                r=execute(r5,state['staged']['path'],apply=True)
                state['audited']=False;apply.disabled=True;approval.value=''
                print('✓ Operación finalizada. No reinició el backend. Informe:',r['report'])
                print('NOTA: R6 es parche operativo, NO promoción de versión del núcleo Git.')
            except Exception as ex:print('✗:',type(ex).__name__,str(ex))
    apply.on_click(on_apply)
    display(w.VBox([header,picker,drive_path,w.HBox([from_drive,git]),
                    w.HBox([inspect,apply]),approval,output]))
    return state
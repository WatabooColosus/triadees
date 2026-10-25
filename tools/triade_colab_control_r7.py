"""Tríade Ω · Centro de Control R7 para Google Colab.

Respeta el arranque R5 PIN y la recuperación V2. Permite restablecer una copia
WAL-safe más reciente SOLO si supera identidad, hash, linaje y mínimos conocidos.
El código de versiones se rehidrata desde commits inmutables de Git.
No promete continuidad de procesos cuando Colab termina el kernel.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading
import urllib.request

VERSION = 'R7.0-panel-candidate'
PIN = '8fdd397b09d7c7da5da8db30235ce626d6a271ec'
REHYDRATOR_COMMIT = 'ada140cf2fad8926e33843540570a1e02494c7fe'
REHYDRATOR_PATH = 'tools/triade_colab_continuity_r631.py'
MIN_OBSERVED = {'neuron_activity': 6, 'neuron_education_applications': 15}
GUARD_TABLES = ('auth_users', 'auth_email_identities', 'neurons', 'autonomous_tasks', 'neuron_education_sessions', 'neuron_education_applications', 'metabolic_cycle', 'worker_runs', 'governed_research_runs')
REPO = 'https://github.com/WatabooColosus/triadees.git'


def _check_api(url: str, timeout: float = 2.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except (OSError, ValueError, TimeoutError):
        return False


def _read_json(path: Path):
    if not path.is_file() or path.is_symlink():
        return None
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _counts(path: Path):
    if not path.is_file() or path.is_symlink():
        raise RuntimeError('Imagen de Bodega no disponible o insegura')
    with contextlib.closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=20)) as conn:
        if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('Bodega SQLite inconsistente')
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = set(GUARD_TABLES) - tables
        if missing:
            raise RuntimeError('Faltan tablas básicas: ' + ','.join(sorted(missing)))
        counts = {t: conn.execute('SELECT COUNT(*) FROM "' + t + '"').fetchone()[0] for t in GUARD_TABLES}
        counts.update({'neuron_activity': conn.execute('SELECT COUNT(*) FROM neuron_activity WHERE activated=1').fetchone()[0] if 'neuron_activity' in tables else 0})
        return counts


def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as data:
        for block in iter(lambda: data.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def _git(root, *args, timeout=150):
    result = subprocess.run(['git', '-C', str(root), *args], check=False, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Git: ' + result.stderr.decode(errors='replace')[-400:])
    return result.stdout


def _dominates(a, b):
    return all(a.get(k, 0) >= b.get(k, 0) for k in GUARD_TABLES)


class Center:
    def __init__(self, r5):
        self.r5 = r5
        self.root = Path(r5.ROOT)
        self.work = Path(r5.WORK)
        self.drive = Path(r5.BASE)
        self.db = Path(r5.DB)
        self.lock = threading.RLock()
        self.pin_sha = PIN

    def _sync_paths(self):
        self.root = Path(self.r5.ROOT)
        self.work = Path(self.r5.WORK)
        self.drive = Path(self.r5.BASE)
        self.db = Path(self.r5.DB)

    def _origin_verified(self):
        self._sync_paths()
        if not (self.root / '.git').is_dir():
            return False
        return _git(self.root, 'rev-parse', 'HEAD').decode().strip() == PIN and _git(self.root, 'remote', 'get-url', 'origin').decode().strip() in (REPO, REPO[:-4])

    def _checkpoint_index(self):
        """Return the last *review* snapshot, never an unverified file by filename."""
        proof = _read_json(self.work / 'restore_proof.json')
        if not proof or not proof.get('source_sha256'):
            return None
        base = self.drive / 'operacion_colab_r5' / 'ramas_en_revision' / str(proof['source_sha256'])[:16]
        pointer = _read_json(base / 'latest_review.json')
        if not pointer:
            return None
        filename = pointer.get('file')
        if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith('.sqlite3'):
            raise RuntimeError('Índice de respaldo con ruta insegura')
        image = base / filename
        metadata = _read_json(image.with_suffix('.json'))
        if (pointer.get('status') != 'review_branch_only' or metadata != pointer
                or pointer.get('lineage') != '90e9a51dd7ffef31'
                or pointer.get('source_v2_sha256') != proof.get('source_sha256')
                or pointer.get('code_sha') != PIN):
            raise RuntimeError('Respaldo no pertenece al origen certificado')
        if not image.is_file() or image.is_symlink() or (Path(str(image) + '-wal').exists()):
            raise RuntimeError('Imagen Drive insegura o con WAL lateral')
        if len(str(pointer.get('sha256', ''))) != 64 or _sha(image) != pointer['sha256']:
            raise RuntimeError('Huella SHA del respaldo de Drive no coincide')
        info = self.r5.db_info(image)
        if info.get('status') != 'ok' or info.get('owner_fingerprint') != proof.get('owner_fingerprint'):
            raise RuntimeError('Identidad o SQLite inválida en respaldo de Drive')
        observed = _counts(image)
        for table, value in pointer.get('counts', {}).items():
            if observed.get(table) != value:
                raise RuntimeError('Recuento del respaldo y del manifiesto divergente: ' + table)
        self.r5._owner_account_status(image)
        return {'file': image, 'counts': observed, 'sha256': pointer['sha256'], 'record': pointer}

    def _floor(self):
        floor = dict(MIN_OBSERVED)
        manifest = _read_json(self.drive / 'operacion_colab_r7' / 'last_success.json')
        if manifest and manifest.get('lineage') == '90e9a51dd7ffef31':
            for key, value in manifest.get('observed_counts', {}).items():
                if key in (*GUARD_TABLES, 'neuron_activity') and isinstance(value, int):
                    floor[key] = max(floor.get(key, 0), value)
        return floor

    def status(self):
        self._sync_paths()
        result = {'panel': VERSION, 'code_checkout': 'absent', 'kernel': 'connected',
                  'api_http_200': _check_api('http://127.0.0.1:8010/health/live'),
                  'ollama_http_200': _check_api('http://127.0.0.1:11434/api/tags'),
                  'drive_mounted': self.drive.is_dir(), 'bodega': 'absent',
                  'release': 'R5 (sin superposición certificada)', 'guardian': 'not_certified'}
        try:
            if self._origin_verified():
                result['code_checkout'] = 'R5 pinned ' + PIN[:12]
        except (OSError, RuntimeError):
            result['code_checkout'] = 'conflicto de commit/origen'
        if self.db.is_file():
            try:
                counts = _counts(self.db)
                self.r5._owner_account_status(self.db)
                result.update(bodega='SQLite ok / propietario validado', counts=counts)
                missing = {k: v for k, v in self._floor().items() if counts.get(k, 0) < v}
                result['known_regression'] = missing or None
            except (RuntimeError, sqlite3.Error) as ex:
                result['bodega'] = 'BLOQUEADA: ' + str(ex)[:150]
        meta = _read_json(self.work / 'actualizaciones' / 'continuidad_git_r631.json')
        if meta and meta.get('status') == 'rehydrated_candidate':
            result['release'] = 'R6.3.1 candidata / Git ' + str(meta.get('r631_source', ''))[:10]
        else:
            for tag in ('r63_active.json', 'r62_active.json'):
                st = _read_json(self.work / 'actualizaciones' / tag)
                if st and st.get('status') == 'active_candidate':
                    result['release'] = ('R6.3 candidata' if 'r63' in tag else 'R6.2 candidata')
                    break
        guardian = _read_json(self.work / 'r5_guardian.json')
        if guardian:
            result['guardian'] = 'PID registrado ' + str(guardian.get('pid', 'sin ID')) + ' (actividad no comprobada)'
        if self.drive.is_dir():
            try:
                v2 = _read_json(self.drive / 'continuidad_runtime' / 'v2' / 'active_verified.json')
                result['drive_v2_image'] = v2.get('file') if v2 else 'índice ausente'
                record = self._checkpoint_index() if (self.work / 'restore_proof.json').exists() else None
                result['drive_last_guarded_backup'] = record['file'].name if record else 'no comprobado'
            except (RuntimeError, sqlite3.Error) as ex:
                result['drive_last_guarded_backup'] = 'error: ' + str(ex)[:160]
        return result

    def _restore_best_before_api(self):
        """Replace only the just-restored V2 local copy, with a strictly verifiable later image."""
        self._sync_paths()
        if _check_api('http://127.0.0.1:8010/health/live'):
            raise RuntimeError('API activa: nunca sustituir Bodega viva')
        proof = _read_json(self.work / 'restore_proof.json')
        if not proof:
            raise RuntimeError('R5 aún no acreditó restauración; sin cambios')
        self.r5.check_working_identity()
        prior = _counts(self.db)
        review = self._checkpoint_index()
        chosen = None
        if review is not None:
            if not _dominates(review['counts'], prior):
                raise RuntimeError('Respaldo de revisión no supera al V2 en todas las tablas; revisión manual')
            if any(review['counts'][x] > prior[x] for x in GUARD_TABLES):
                chosen = review
        if chosen is None:
            failures = {k: n for k, n in self._floor().items() if prior.get(k, 0) < n}
            if failures:
                raise RuntimeError('V2 retrocede y no hay copia revisada más reciente acreditada: ' + str(failures))
            return {'result': 'V2 local validada y suficiente; no se reemplazó', 'counts': prior}
        current = chosen['counts']
        failures = {k: n for k, n in self._floor().items() if current.get(k, 0) < n}
        if failures:
            raise RuntimeError('La copia Drive más reciente sigue siendo antigua: ' + str(failures))
        # Close SQLite source, use an isolated backup and fsync replacement with WAL absent.
        if Path(str(self.db) + '-wal').exists() or Path(str(self.db) + '-shm').exists():
            raise RuntimeError('WAL/SHM local presente: restauración bloqueada antes del backend')
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        vault = self.work / 'control_r7' / 'before_review_restore' / stamp
        vault.mkdir(parents=True, exist_ok=False)
        backup = vault / 'v2_pre_restore.sqlite3'
        with contextlib.closing(sqlite3.connect(self.db)) as src, contextlib.closing(sqlite3.connect(backup)) as dst:
            src.backup(dst, pages=128, sleep=0.1)
        if _counts(backup) != prior:
            raise RuntimeError('Backup local previo incompleto; DB original conservada')
        staged = vault / 'review_staged.sqlite3'
        shutil.copy2(chosen['file'], staged)
        if _sha(staged) != chosen['sha256'] or _counts(staged) != current:
            raise RuntimeError('SHA o recuentos de imagen staged divergentes')
        self.r5._owner_account_status(staged)
        os.replace(staged, self.db)
        if _counts(self.db) != current:
            raise RuntimeError('Imagen restaurada no coincide; no arrancar API')
        self.r5.check_working_identity()
        receipt = {'status': 'review_restored_validated', 'file': chosen['file'].name,
                   'sha256': chosen['sha256'], 'backup_original': str(backup), 'counts': current}
        self._write_local(self.work / 'control_r7' / 'last_restore.json', receipt)
        return receipt

    @staticmethod
    def _write_local(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + '.partial')
        if tmp.exists() or tmp.is_symlink():
            raise RuntimeError('Archivo temporal anterior en conflicto: ' + str(tmp))
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, path)

    def start(self):
        """Start from R5 verified Drive, upgrade to pinned code, leave workers owned by backend."""
        with self.lock:
            self._sync_paths()
            if _check_api('http://127.0.0.1:8010/health/live'):
                current = self.status()
                if current.get('bodega', '').startswith('BLOQUEADA'):
                    raise RuntimeError('API viva con Bodega no acreditada: intervención manual')
                updated = self.install_release() if 'R6.3.1' not in current.get('release', '') else {'state': 'already_installed'}
                guardian = self.r5.start_guardian()
                return {'state': 'already_running_verified', 'release': updated, 'guardian': guardian, 'status': self.status()}
            self.r5.install_first()
            self._sync_paths()
            self.r5.connect_verified_v2()
            reviewed = self._restore_best_before_api()
            self.r5.model_ready()
            self.r5.start_real_backend()
            if not _check_api('http://127.0.0.1:8010/health/live'):
                raise RuntimeError('La API R5 no confirmó HTTP 200')
            receipt = self.install_release()
            if receipt.get('state') not in ('already_installed',) and receipt.get('status') != 'rehydrated_candidate':
                raise RuntimeError('No se acreditó la versión restaurada; conservar registros para revisar')
            guardian = self.r5.start_guardian()
            return {'state': 'running_version_rehydrated', 'restore': reviewed, 'release': receipt, 'guardian': guardian, 'status': self.status()}

    def install_release(self):
        """Only R6.3.1 audited immutable chain; never change V2 or install moving main."""
        with self.lock:
            if not self._origin_verified():
                raise RuntimeError('No hay checkout R5 oficial. Arranca R5 primero.')
            if not _check_api('http://127.0.0.1:8010/health/live'):
                raise RuntimeError('Arranca primero la API autenticada R5')
            counts = _counts(self.db)
            missing = {k: v for k, v in self._floor().items() if counts.get(k, 0) < v}
            if missing:
                raise RuntimeError('Memoria retrocedida. No actualizar: ' + str(missing))
            existing = _read_json(self.work / 'actualizaciones' / 'continuidad_git_r631.json')
            if existing and existing.get('status') == 'rehydrated_candidate':
                return {'state': 'already_installed', 'status': self.status()}
            _git(self.root, 'fetch', '--no-tags', '--depth', '1', 'origin', REHYDRATOR_COMMIT)
            if _git(self.root, 'rev-parse', 'FETCH_HEAD').decode().strip() != REHYDRATOR_COMMIT:
                raise RuntimeError('La versión Git no coincide con el commit fijado')
            source = _git(self.root, 'show', REHYDRATOR_COMMIT + ':' + REHYDRATOR_PATH)
            if not 0 < len(source) < 200000:
                raise RuntimeError('Fuente de versión inválida')
            import ast
            import types
            module = types.ModuleType('triade_colab_continuity_r631')
            exec(compile(ast.parse(source.decode('utf-8'), filename=REHYDRATOR_PATH), REHYDRATOR_PATH, 'exec'), module.__dict__)  # noqa: S102 - code is pinned to immutable verified Git SHA
            receipt = module.rehydrate(self.r5)
            if receipt.get('status') != 'rehydrated_candidate' or receipt.get('api_http') != 200:
                raise RuntimeError('Versión candidata no acreditada')
            return receipt

    def check_updates(self):
        """Consult Git only; do not install a moving ref or equate main with candidate."""
        with self.lock:
            self._sync_paths()
            if not (self.root / '.git').is_dir():
                return {'installed': 'Ningún checkout; inicia primero', 'target_pinned': 'R6.3.1', 'remote_main': None}
            fetched = _git(self.root, 'ls-remote', 'origin', 'refs/heads/main').decode().strip()
            remote_sha = fetched.split()[0] if fetched else None
            state = self.status()
            return {'installed': state['release'], 'target_pinned': 'R6.3.1 candidata',
                    'release_source_commit': REHYDRATOR_COMMIT, 'remote_main': remote_sha,
                    'note': 'main puede contener una versión distinta; no se aplica sin nueva auditoría'}

    def save(self):
        with self.lock:
            if not self.drive.is_dir():
                raise RuntimeError('Drive desconectado, no hay respaldo persistente')
            result = self.r5.save_review_copy()
            if not result or result.get('status') not in ('saved_review_only', 'quota', 'too_soon'):
                raise RuntimeError('Guardián no confirmó escritura: ' + str(result))
            return {'guardian': result, 'status': self.status()}

    def start_guardian(self):
        with self.lock:
            return self.r5.start_guardian()

    def record_release(self):
        """Manifest is an observation, not a substitute for an actual snapshot."""
        with self.lock:
            if not self.drive.is_dir() or not self.db.is_file():
                raise RuntimeError('Sin Drive o Bodega')
            counts = _counts(self.db)
            proof = _read_json(self.work / 'restore_proof.json')
            if not proof or not self._origin_verified():
                raise RuntimeError('Sin identidad/checkout R5 acreditados')
            self.r5._owner_account_status(self.db)
            review = self._checkpoint_index()
            if not review:
                raise RuntimeError('No hay imagen de Drive comprobada; no marcar continuidad')
            # La memoria viva puede avanzar durante el guardado. Certificamos la imagen
            # restaurable en Drive, no afirmamos que tenga todos los ciclos presentes.
            manifest = {'schema': 'triade_r7_operational_checkpoint_v1', 'lineage': '90e9a51dd7ffef31',
                        'release': self.status()['release'], 'r5_commit': PIN,
                        'observed_counts': review['counts'], 'snapshot_sha256': review['sha256'],
                        'snapshot_file': review['file'].name, 'written_at': dt.datetime.now(dt.timezone.utc).isoformat()}
            self._write_local(self.drive / 'operacion_colab_r7' / 'last_success.json', manifest)
            return manifest


def render(r5):
    import ipywidgets as w
    from IPython.display import HTML, display, clear_output
    from html import escape
    center = Center(r5)
    display(HTML('''<style>.r7hero{background:linear-gradient(120deg,#071b37,#162354 53%,#38134d);padding:22px;border-radius:18px;border:1px solid #3f8fdd;color:#f0f8ff;font:15px system-ui}
.r7hero h2{color:#6df2ef;margin:0 0 10px}.r7hero small{color:#b1cef0}.r7pill{display:inline-block;border:1px solid #648dc3;border-radius:100px;padding:6px 10px;margin:5px;color:#d4ebff}</style>'''))
    display(HTML('''<div class="r7hero"><h2>TRÍADE Ω · CENTRO DE CONTINUIDAD R7</h2><small>Git = código · Drive = memoria · Colab = ejecución temporal</small><div><span class="r7pill">Versión verificable</span><span class="r7pill">Identidad protegida</span><span class="r7pill">Reinicio seguro</span><span class="r7pill">Sin procesos duplicados</span></div></div>'''))
    info = w.HTML(value='<b>Centro listo. Pulsa «Verificar estado».</b>')
    out = w.Output(layout=w.Layout(border='1px solid #426aac',max_height='460px',overflow='auto',padding='10px'))
    approve = w.Text(placeholder='Para instalar: ACTUALIZAR R6.3.1', description='Autorización', layout=w.Layout(width='96%'))
    busy = w.HTML('')

    def execute(label, fn, require=None):
        with out:
            clear_output(wait=True)
            print('TRÍADE Ω ·', label)
            try:
                if require and approve.value.strip() != require:
                    raise RuntimeError('Autorización requerida: ' + require)
                result = fn()
                print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
                print('✓ Operación concluida. Verifica el resultado real en la salida.')
            except (OSError, RuntimeError, ValueError, sqlite3.Error, subprocess.SubprocessError) as exc:
                print('✗ Operación no acreditada:', type(exc).__name__, str(exc)[:1400])
            info.value = '<b>Panel consultado:</b> ' + escape(dt.datetime.now().strftime('%H:%M:%S'))
            busy.value = ''

    def button(label, fn, color=''):
        b = w.Button(description=label, button_style=color, layout=w.Layout(width='275px',height='41px'))
        def click(_):
            if busy.value:
                return
            busy.value = '<b>Ejecutando acción. Evita pulsar otro botón.</b>'
            execute(label, fn, require='ACTUALIZAR R6.3.1' if fn == center.install_release else None)
        b.on_click(click)
        return b

    controls = [button('Verificar estado / versión', center.status, 'info'),
                button('Buscar versiones en Git', center.check_updates),
                button('Iniciar última versión + memoria', center.start, 'success'),
                button('Actualizar código a R6.3.1', center.install_release, 'warning'),
                button('Abrir frontend privado', center.r5.open_frontend),
                button('Guardar copia verificada', center.save),
                button('Activar guardián Drive', center.start_guardian),
                button('Confirmar punto recuperable', center.record_release),
                button('Auditar actividad real (30 s)', lambda: center.r5.audit_progress(30))]
    display(info, busy, w.Box(controls, layout=w.Layout(display='flex', flex_flow='row wrap',gap='8px')),
            approve, w.HTML('<small>No pide claves. No sustituye el índice V2. Si el kernel se apaga, vuelve a ejecutar esta celda y pulsa «Iniciar / recuperar».</small>'),out)
    return center
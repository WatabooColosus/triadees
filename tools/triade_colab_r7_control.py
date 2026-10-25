"""Tríade Ω R7 Colab Control Center (companion to the audited embedded R5).

No scheduler survives Google Colab VM termination: operator restarts notebook UI.
Git is code authority; Drive is backup authority; only checked live state is active.
Never moves Git HEAD or rewrites V2 canonical indexes or secrets.
"""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import threading
import urllib.request

UI_RELEASE = "R7.0-rc.1"
R5_SHA = "8fdd397b09d7c7da5da8db30235ce626d6a271ec"
R631_BUNDLE = "ada140cf2fad8926e33843540570a1e02494c7fe"
REPO_URL = "https://github.com/WatabooColosus/triadees.git"
R63_ACTIVE_SHA = "777dd370dd8b23f5d93303afa7796ceba51166ba"
R62_ACTIVE_SHA = "860351246340913c5095ab85e7087facadb5a21f"
RELEASES = {"R5 · base protegida": "R5", "R6.3.1 · candidata medida": "R6.3.1-rc"}
WATERMARK_TABLES = ("autonomous_tasks", "auth_users", "auth_email_identities", "neurons", "neuron_education_sessions", "neuron_education_applications", "metabolic_cycle", "worker_runs", "governed_research_runs")


def _json(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except (OSError, UnicodeError, ValueError):
        return None


def _atomic_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise RuntimeError("Ruta de manifiesto insegura")
    payload = json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8")
    tmp = path.with_name("." + path.name + ".partial")
    if tmp.exists() or tmp.is_symlink():
        raise RuntimeError("Manifiesto temporal ocupado")
    try:
        with tmp.open("xb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _url_ok(url, timeout=2):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except (OSError, TimeoutError, ValueError):
        return False


def _db_counts(db):
    db = Path(db)
    if not db.is_file():
        return {}
    with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=12) as con:
        tabs = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result = {key: int(con.execute(f'SELECT COUNT(*) FROM "{key}"').fetchone()[0]) for key in WATERMARK_TABLES if key in tabs}
        if "neuron_activity" in tabs:
            result["activated_neuron_activity"] = int(con.execute("SELECT COUNT(*) FROM neuron_activity WHERE activated=1").fetchone()[0])
        if "worker_events" in tabs:
            result["worker_event_count"] = int(con.execute("SELECT COUNT(*) FROM worker_events").fetchone()[0])
        return result


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(2 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_review(r5):
    """Read and authenticate R5 guardian's latest reviewed, WAL-closed snapshot."""
    proof = _json(r5.WORK / "restore_proof.json")
    if not proof or not proof.get("source_sha256") or not proof.get("owner_fingerprint"):
        return {"status": "unavailable", "reason": "Sin prueba R5 de restauración"}
    base = Path(r5.BASE)
    review = base / "operacion_colab_r5" / "ramas_en_revision" / str(proof["source_sha256"])[:16]
    index = _json(review / "latest_review.json")
    if not index:
        return {"status": "unavailable", "reason": "Guardián todavía no tiene copia revisada en Drive"}
    name = index.get("file")
    if (index.get("status") != "review_branch_only" or
        index.get("source_v2_sha256") != proof["source_sha256"] or
        index.get("lineage") != "90e9a51dd7ffef31" or
        not isinstance(name, str) or Path(name).name != name or
        not name.endswith(".sqlite3")):
        return {"status": "blocked", "reason": "Índice del guardián inválido o de otro linaje"}
    source = review / name
    if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(review.resolve()):
        return {"status": "blocked", "reason": "Imagen ausente o ruta insegura"}
    if source.with_suffix(".json").is_symlink():
        return {"status": "blocked", "reason": "Manifiesto lateral inseguro"}
    sidecar = _json(source.with_suffix(".json"))
    if not sidecar or sidecar != index:
        return {"status": "blocked", "reason": "Índice y manifiesto lateral no coinciden"}
    if _sha(source) != index.get("sha256"):
        return {"status": "blocked", "reason": "SHA-256 de respaldo Drive divergente"}
    info = r5.db_info(source)
    if info.get("status") != "ok" or info.get("owner_fingerprint") != proof["owner_fingerprint"]:
        return {"status": "blocked", "reason": "SQLite/identidad de respaldo no acreditada"}
    if info.get("counts") != index.get("counts"):
        return {"status": "blocked", "reason": "Conteos del índice no coinciden con SQLite"}
    for key, value in proof.get("counts", {}).items():
        if info["counts"].get(key, 0) < value:
            return {"status": "blocked", "reason": "Regresión frente a Bodega V2: " + str(key)}
    r5._owner_account_status(source)
    return {"status": "verified", "path": str(source), "sha256": index["sha256"],
            "counts": _db_counts(source), "date": index.get("date"), "source": "R5"}



def _verify_r7(r5):
    proof = _json(Path(r5.WORK) / "restore_proof.json")
    if not proof or not proof.get("source_sha256"):
        return {"status": "unavailable", "reason": "Sin origen V2 comprobado"}
    home = Path(r5.BASE) / "operacion_colab_r7" / "snapshots" / proof["source_sha256"][:16]
    manifest = _json(home / "latest_verified.json")
    if not manifest:
        return {"status": "unavailable", "reason": "Aún no hay respaldo R7"}
    name = manifest.get("file")
    if not (manifest.get("status") == "r7_verified_sqlite" and
            manifest.get("source_v2_sha256") == proof["source_sha256"] and
            manifest.get("lineage") == "90e9a51dd7ffef31" and
            isinstance(name, str) and Path(name).name == name and name.endswith(".sqlite3")):
        return {"status": "blocked", "reason": "Manifiesto R7 con linaje o ruta inválidos"}
    path = home / name
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(home.resolve()):
        return {"status": "blocked", "reason": "Imagen R7 ausente o insegura"}
    sidecar = _json(path.with_suffix(".json"))
    if sidecar != manifest or _sha(path) != manifest.get("sha256"):
        return {"status": "blocked", "reason": "Hash o manifiesto de copia R7 inválido"}
    info = r5.db_info(path)
    if info.get("status") != "ok" or info.get("owner_fingerprint") != proof.get("owner_fingerprint"):
        return {"status": "blocked", "reason": "Bodega R7 no íntegra o identidad divergente"}
    if info.get("counts") != manifest.get("counts"):
        return {"status": "blocked", "reason": "Conteos de respaldo R7 divergentes"}
    r5._owner_account_status(path)
    return {"status": "verified", "path": str(path), "sha256": manifest["sha256"],
            "counts": _db_counts(path), "date": manifest.get("date"), "source": "R7"}


def _best_verified_snapshot(r5):
    options = (_verify_review(r5), _verify_r7(r5))
    blocked = [x for x in options if x["status"] == "blocked"]
    if blocked:
        raise RuntimeError("Respaldo con conflicto de integridad: " + str(blocked))
    verified = [x for x in options if x["status"] == "verified"]
    if not verified:
        return {"status": "unavailable", "reason": "No hay copias periódicas verificadas; se usa V2"}
    for x in verified:
        for other in verified:
            if x is other:
                continue
            a, b = x["counts"], other["counts"]
            inc = any(a.get(k, 0) > b.get(k, 0) for k in WATERMARK_TABLES)
            dec = any(a.get(k, 0) < b.get(k, 0) for k in WATERMARK_TABLES)
            if inc and dec:
                raise RuntimeError("Respaldo R5 y R7 divergentes; evitar elección automática")
    return max(verified, key=lambda x: (sum(x["counts"].get(k, 0) for k in WATERMARK_TABLES),str(x.get("date", ""))))


_R7_GUARDIAN_THREAD = None
_R7_GUARDIAN_STOP = threading.Event()
_R7_LOCK = threading.Lock()


def _save_r7_snapshot(r5):
    """Make a consistent SQLite online backup; publish hash-checked Drive pointer last."""
    proof = _json(Path(r5.WORK) / "restore_proof.json")
    if not proof or not proof.get("owner_fingerprint"):
        raise RuntimeError("Bodega sin prueba de propietario único")
    live = Path(r5.DB)
    info = r5.db_info(live, allow_live_wal=True)
    if info.get("status") != "ok" or info.get("owner_fingerprint") != proof["owner_fingerprint"]:
        raise RuntimeError("Bodega viva no íntegra o de propietario distinto")
    home = Path(r5.BASE) / "operacion_colab_r7" / "snapshots" / proof["source_sha256"][:16]
    home.mkdir(parents=True, exist_ok=True)
    if home.is_symlink():
        raise RuntimeError("Ruta de backup insegura")
    prior = _verify_r7(r5)
    if prior["status"] == "blocked":
        raise RuntimeError("Respaldo R7 previo inválido; sin sobrescribir su puntero")
    current = _db_counts(live)
    if prior["status"] == "verified":
        old = prior["counts"]
        lost = {k:(v,current.get(k,0)) for k,v in old.items() if current.get(k,0)<v}
        if lost:
            raise RuntimeError("Bodega regresó frente al último respaldo R7: " + str(lost))
    stamp = dt.datetime.now(dt.timezone.utc)
    name = "r7-" + stamp.strftime("%Y%m%dT%H%M%S%fZ") + ".sqlite3"
    with tempfile.TemporaryDirectory(prefix="triade-r7-", dir="/content" if Path("/content").is_dir() else None) as td:
        image = Path(td) / name
        with sqlite3.connect(live.resolve().as_uri() + "?mode=ro", uri=True, timeout=60) as source, sqlite3.connect(image, timeout=60) as dst:
            source.backup(dst, pages=128, sleep=0.1)
        result = r5.db_info(image)
        if result.get("status") != "ok" or result.get("owner_fingerprint") != proof["owner_fingerprint"]:
            raise RuntimeError("Imagen SQLite de respaldo no acreditada")
        counts = result["counts"]
        for k,v in proof.get("counts",{}).items():
            if counts.get(k,0) < v:
                raise RuntimeError("Respaldo regresó respecto a V2: " + k)
        if prior["status"] == "verified":
            for k,v in prior["counts"].items():
                if k in counts and counts[k] < v:
                    raise RuntimeError("Respaldo regresó frente a última copia: " + k)
        digest = _sha(image)
        free = shutil.disk_usage(home).free
        if free < max(32*1024*1024, image.stat().st_size*2):
            raise RuntimeError("Drive sin espacio suficiente para respaldo seguro")
        temp_dest = home / ("."+name+".partial")
        dest = home / name
        if temp_dest.exists() or dest.exists():
            raise RuntimeError("Nombre de backup ya utilizado")
        try:
            shutil.copyfile(image,temp_dest)
            if _sha(temp_dest) != digest:
                raise RuntimeError("SHA Drive difiere de copia local")
            os.replace(temp_dest,dest)
        finally:
            temp_dest.unlink(missing_ok=True)
        if _sha(dest) != digest or r5.db_info(dest).get("status") != "ok":
            raise RuntimeError("Copia Drive no verificable; índice previo intacto")
        manifest = {"status":"r7_verified_sqlite", "lineage":"90e9a51dd7ffef31",
                    "source_v2_sha256":proof["source_sha256"], "sha256":digest,
                    "counts":counts, "file":name,"date":stamp.isoformat(),
                    "runtime_version":inspect(r5)["version_codigo_runtime"]}
        _atomic_json(dest.with_suffix(".json"),manifest)
        _atomic_json(home / "latest_verified.json",manifest)
        return {"status":"verified_backup_saved","file":str(dest),"sha256_prefix":digest[:12],"counts":counts}


def start_r7_guardian(r5, *, interval=600):
    global _R7_GUARDIAN_THREAD
    if _R7_GUARDIAN_THREAD is not None and _R7_GUARDIAN_THREAD.is_alive():
        return {"status":"already_running"}
    # Never run alongside the legacy R5 backup process.
    legacy = _json(Path(r5.WORK) / "r5_guardian.json")
    if legacy:
        try:
            import psutil
            process = psutil.Process(int(legacy["pid"]))
            if process.is_running() and "triade_colab_r5.py" in " ".join(process.cmdline()):
                return {"status":"deferred_existing_r5_guardian","interval_sec":600}
        except (ImportError,OSError,ValueError,KeyError):
            pass
    # Backup immediately: don't mark user-visible success before Drive verifies.
    result = _save_r7_snapshot(r5)
    _atomic_json(Path(r5.WORK) / "r7" / "ultimo_backup.json", result)
    _R7_GUARDIAN_STOP.clear()
    def cycle():
        while not _R7_GUARDIAN_STOP.wait(interval):
            try:
                with _R7_LOCK:
                    saved = _save_r7_snapshot(r5)
                    _atomic_json(Path(r5.WORK) / "r7" / "ultimo_backup.json",saved)
                    save_state(r5)
            except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
                _atomic_json(Path(r5.WORK)/"r7"/"guardian_error.json",{"at":dt.datetime.now(dt.timezone.utc).isoformat(),"type":type(exc).__name__,"error":str(exc)[:350]})
    _R7_GUARDIAN_THREAD = threading.Thread(target=cycle, name="triade-r7-guardian-verified", daemon=True)
    _R7_GUARDIAN_THREAD.start()
    return {"status":"started","first":result,"interval_sec":interval}

def _highwater(r5):
    return _json(Path(r5.BASE) / "operacion_colab_r7" / "ultimo_estado_observado.json")


def inspect(r5):
    root = Path(r5.ROOT)
    db = Path(r5.DB)
    work = Path(r5.WORK)
    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=6, check=False)
        code_sha = head.stdout.strip() if head.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        code_sha = None
    r62 = _json(work / "actualizaciones" / "r62_active.json") or {}
    r63 = _json(work / "actualizaciones" / "r63_active.json") or {}
    r631 = _json(work / "actualizaciones" / "r631_stage" / "installed.json") or {}
    release = ("R6.3.1-rc" if r631.get("status") == "cli_hotfix_ready" else
               "R6.3-rc" if r63.get("candidate_commit") == R63_ACTIVE_SHA else
               "R6.2-rc" if r62.get("candidate_commit") == R62_ACTIVE_SHA else
               "R5.0" if code_sha == R5_SHA else "desconocido")
    saved = _json(Path(r5.BASE) / "operacion_colab_r7" / "version_preferida.json") or {}
    dbinfo = r5.db_info(db, allow_live_wal=True) if db.is_file() else {}
    counts = _db_counts(db) if dbinfo.get("status") == "ok" else {}
    return {"panel": UI_RELEASE, "git_head": code_sha, "version_codigo_runtime": release,
            "version_deseada_drive": saved.get("version", "no seleccionada"),
            "drive_montado": Path(r5.BASE).is_dir(),
            "memoria_integridad": dbinfo.get("status", "ausente"),
            "bodega_sesion": db.is_file(), "neuronas": counts.get("neurons"),
            "activaciones": counts.get("activated_neuron_activity"),
            "aplicaciones": counts.get("neuron_education_applications"),
            "tareas": counts.get("autonomous_tasks"),
            "api_8010": _url_ok("http://127.0.0.1:8010/health/live"),
            "ollama_11434": _url_ok("http://127.0.0.1:11434/api/tags"),
            "guardian_local": _json(work / "r5_guardian.json") is not None,
            "guardian_r7_en_ejecucion": bool(_R7_GUARDIAN_THREAD is not None and _R7_GUARDIAN_THREAD.is_alive()),
            "backup_r7_ultimo": (_json(work / "r7" / "ultimo_backup.json") or {}).get("status", "sin_confirmar")}


def _check_highwater(r5, selected, *, acknowledge_loss=False):
    last = _highwater(r5)
    if not last or not isinstance(last.get("counts"), dict):
        return None
    previous = last["counts"]
    regressed = {key: (previous[key], selected.get(key, 0)) for key in previous
                 if isinstance(previous[key], int) and selected.get(key, 0) < previous[key]}
    if regressed and not acknowledge_loss:
        raise RuntimeError("La copia recuperable es más antigua que el último estado visto en Drive: "
                           + str(regressed) + ". No se recuperarán eventos no respaldados automáticamente. "
                           "Revisa los respaldos; la continuidad está BLOQUEADA.")
    return regressed


def restore_best_review(r5, *, acknowledge_loss=False):
    """Only before API begins; promote newer authenticated guard-review snapshot."""
    if _url_ok("http://127.0.0.1:8010/health/live", timeout=1):
        raise RuntimeError("API ya activa: no reemplazar Bodega en caliente")
    review = _best_verified_snapshot(r5)
    db = Path(r5.DB)
    live_info = r5.db_info(db, allow_live_wal=True)
    if live_info.get("status") != "ok":
        raise RuntimeError("Bodega local no verificada, revisar continuidad R5")
    current = _db_counts(db)
    if review["status"] != "verified":
        _check_highwater(r5, current, acknowledge_loss=acknowledge_loss)
        return {"status": "keep_r5_v2", "reason": review["reason"], "counts": current}
    new = review["counts"]
    # Monotone counts are necessary (not sufficient) to share the same lineage.
    lower = {k: (new.get(k, 0), old) for k, old in current.items()
             if k in new and new.get(k, 0) < old}
    if lower:
        _check_highwater(r5, current, acknowledge_loss=acknowledge_loss)
        return {"status": "keep_newer_local", "review_behind": lower, "counts": current}
    _check_highwater(r5, new, acknowledge_loss=acknowledge_loss)
    if all(new.get(k, 0) == old for k, old in current.items() if k in new):
        # Equal counts are not proof of equal content: keep local unless hashes match.
        if _sha(db) != review["sha256"]:
            return {"status": "keep_local_equal_counts", "note": "No sobrescribir contenido divergente"}
        return {"status": "already_restored", "sha256": review["sha256"]}
    for suffix in ("-wal", "-shm"):
        side = Path(str(db) + suffix)
        if side.is_file() and side.stat().st_size:
            raise RuntimeError("SQLite local tiene sidecar activo: no restaurar en caliente")
    stage = db.with_name("." + db.name + ".r7-staged")
    if stage.exists() or stage.is_symlink():
        raise RuntimeError("Archivo de staging ocupado")
    # Preserved local backup even when chosen guardian snapshot is more complete.
    folder = Path(r5.WORK) / "r7" / "rollback"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = folder / ("antes_de_recuperar_" + stamp + ".sqlite3")
    with sqlite3.connect(db) as src, sqlite3.connect(backup) as dst:
        src.backup(dst)
    if r5.db_info(backup).get("status") != "ok":
        raise RuntimeError("Copia de seguridad local inválida; no modificar")
    try:
        shutil.copyfile(review["path"], stage)
        if _sha(stage) != review["sha256"]:
            raise RuntimeError("Error de transferencia desde Drive")
        if r5.db_info(stage).get("status") != "ok":
            raise RuntimeError("Imagen staged no íntegra")
        os.replace(stage, db)
    finally:
        stage.unlink(missing_ok=True)
    r5._owner_account_status(db)
    r5.check_working_identity()
    record = {"status": "restored_review_guardian", "date": dt.datetime.now(dt.timezone.utc).isoformat(),
              "guardian_sha256": review["sha256"], "backup_local": str(backup),
              "counts": _db_counts(db), "v2_index_unchanged": True}
    _atomic_json(Path(r5.WORK) / "r7" / "restauracion.json", record)
    return record


def _git_verified_source(r5, *, commit, path):
    root = Path(r5.ROOT)
    origin = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                            capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    if origin not in (REPO_URL, REPO_URL.removesuffix(".git")):
        raise RuntimeError("Repositorio Git no corresponde a Tríade")
    subprocess.run(["git", "-C", str(root), "fetch", "--depth", "1", "origin", commit], check=True, timeout=180)
    current = subprocess.check_output(["git", "-C", str(root), "rev-parse", "FETCH_HEAD"], text=True).strip()
    if current != commit:
        raise RuntimeError("Git entregó commit distinto")
    blob = subprocess.check_output(["git", "-C", str(root), "show", commit + ":" + path], timeout=35)
    if not 0 < len(blob) < 200000:
        raise RuntimeError("Fuente fuera de límites")
    return blob


def apply_candidate(r5):
    """Explicitly elected candidate; existing verified updaters handle API ownership."""
    if not (Path(r5.WORK) / "r5_continuity.json").is_file():
        raise RuntimeError("Primero restaurar y acreditar memoria R5")
    if not _url_ok("http://127.0.0.1:8010/health/live"):
        raise RuntimeError("API no iniciada; no actualizar código a medias")
    code = _git_verified_source(r5, commit=R631_BUNDLE, path="tools/triade_colab_continuity_r631.py")
    ast.parse(code.decode("utf-8"), filename="tools/triade_colab_continuity_r631.py")
    namespace = {"__name__": "triade_r631_continuity_pinned"}
    exec(compile(code.decode("utf-8"), "triade_colab_continuity_r631.py", "exec"), namespace)  # noqa: S102
    result = namespace["rehydrate"](r5)
    if result.get("status") != "rehydrated_candidate" or result.get("api_http") != 200:
        raise RuntimeError("Rehidratación candidata sin verificación completa")
    return result


def save_state(r5):
    """Durable watermark only: never claims unsaved state is recoverable."""
    st = inspect(r5)
    if st["memoria_integridad"] != "ok":
        raise RuntimeError("No hay Bodega acreditada")
    proof = _json(Path(r5.WORK) / "restore_proof.json")
    if not proof:
        raise RuntimeError("Sin restauración acreditada R5")
    db = Path(r5.DB)
    counts = _db_counts(db)
    target = Path(r5.BASE) / "operacion_colab_r7" / "ultimo_estado_observado.json"
    old = _json(target)
    if old and isinstance(old.get("counts"), dict):
        for k, v in old["counts"].items():
            if isinstance(v, int) and counts.get(k, 0) < v:
                raise RuntimeError("No actualizar marca de continuidad con datos más antiguos: " + k)
    record = {"status": "observed_not_backed_up", "date": dt.datetime.now(dt.timezone.utc).isoformat(),
              "counts": counts, "origin_sha256": proof.get("source_sha256"),
              "runtime_version": st["version_codigo_runtime"],
              "note": "Una marca de agua NO es una copia restaurable; requerirá imagen SQLite acreditada."}
    _atomic_json(target, record)
    return record


def set_preference(r5, version):
    if version not in RELEASES.values():
        raise RuntimeError("Versión fuera de catálogo fijado")
    if not Path(r5.BASE).is_dir():
        raise RuntimeError("Conecta Drive antes de conservar una versión")
    path = Path(r5.BASE) / "operacion_colab_r7" / "version_preferida.json"
    record = {"version": version, "source": "seleccion_explicita_usuario", "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "commit_bundle": R631_BUNDLE if version == "R6.3.1-rc" else R5_SHA}
    _atomic_json(path, record)
    return record


def boot(r5, *, chosen=None, allow_older_backup=False, reporter=print):
    """Resume in this VM; no claim of running while Google Colab is disconnected."""
    reporter("1/6 · Comprobando núcleo R5 (Git SHA inmutable)…")
    if not r5._is_installed():
        r5.install_first()
    reporter("2/6 · Verificando Drive, imagen V2 y propietario…")
    if not (Path(r5.WORK) / "r5_continuity.json").is_file():
        r5.connect_verified_v2()
    reporter("3/6 · Buscando última copia íntegra del guardián…")
    if not _url_ok("http://127.0.0.1:8010/health/live"):
        restore = restore_best_review(r5, acknowledge_loss=allow_older_backup)
    else:
        restore = {"status": "api_running_no_db_swap"}
    reporter("Bodega: " + json.dumps(restore, ensure_ascii=False)[:500])
    reporter("4/6 · Comprobando Ollama…")
    if not _url_ok("http://127.0.0.1:11434/api/tags"):
        r5.model_ready()
    reporter("5/6 · Arrancando API y guardián del runtime…")
    if not _url_ok("http://127.0.0.1:8010/health/live"):
        r5.start_real_backend()
    reporter("6/6 · Verificando versión elegida…")
    requested = chosen or (_json(Path(r5.BASE) / "operacion_colab_r7" / "version_preferida.json") or {}).get("version") or "R5"
    if requested == "R6.3.1-rc" and inspect(r5)["version_codigo_runtime"] != "R6.3.1-rc":
        reporter("Cargando candidato R6.3.1 desde Git con validaciones y respaldos propios…")
        apply_candidate(r5)
    elif requested != "R5" and requested != "R6.3.1-rc":
        raise RuntimeError("Versión deseada desconocida. No se cambia de código")
    st = inspect(r5)
    if not (st["api_8010"] and st["bodega_sesion"] and st["memoria_integridad"] == "ok"):
        raise RuntimeError("El backend o SQLite no superó la verificación final")
    save_state(r5)
    try:
        guard = start_r7_guardian(r5)
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        guard = {"status": "degraded_no_backup", "reason": type(exc).__name__ + ": " + str(exc)[:250]}
        _atomic_json(Path(r5.WORK) / "r7" / "guardian_error.json",guard)
    reporter("Guardián Drive: " + json.dumps(guard, ensure_ascii=False)[:350])
    reporter("✓ Tríade encendida en este runtime. Los workers requieren auditoría de dos lecturas.")
    return st


def show_panel(r5):
    import ipywidgets as w
    from IPython.display import HTML, clear_output, display
    import html

    banner = w.HTML('''<div style="background:linear-gradient(125deg,#05162c,#0c3060 60%,#39104f);color:#fff;border:1px solid #43cde6;border-radius:15px;padding:16px;font:14px system-ui">
    <div style="font-size:22px;font-weight:bold">TRÍADE Ω · CENTRO DE CONTROL R7</div>
    <div style="color:#9be9ff;margin-top:4px">Git = código · Drive = memoria · Colab = ejecución temporal</div>
    <div style="margin-top:8px">Iniciar / Recuperar · Versiones · Actualizaciones · Bodega · Workers · Respaldos</div></div>''')
    state = w.HTML()
    desired = w.Dropdown(description="Versión:", options=[(label,val) for label,val in RELEASES.items()], value="R5", style={"description_width":"initial"}, layout=w.Layout(width="100%"))
    approve = w.Text(description="Autorización:", placeholder="ACTUALIZAR R6.3.1", style={"description_width":"initial"}, layout=w.Layout(width="100%"))
    output = w.Output(layout=w.Layout(border="1px solid #365a83", padding="8px", max_height="420px", overflow="auto"))
    buttons = []
    busy = threading.Lock()

    def refresh():
        info = inspect(r5)
        color = "#24b8a1" if info["api_8010"] and info["memoria_integridad"] == "ok" else "#e5a741"
        details = " · ".join(f"{html.escape(str(k))}: <b>{html.escape(str(v))}</b>" for k,v in info.items() if k in ("version_codigo_runtime","version_deseada_drive","api_8010","ollama_11434","memoria_integridad","neuronas","activaciones","aplicaciones","tareas"))
        state.value = f'<div style="border-left:4px solid {color};padding:11px;background:#0d1b33;color:#ecf4fc;font:13px system-ui">{details}</div>'
        return info

    def action(label, func, width="215px"):
        button = w.Button(description=label, layout=w.Layout(width=width, height="39px"))
        def clicked(_):
            if not busy.acquire(blocking=False):
                with output:
                    print("Otra operación está en curso; no duplicar servicios.")
                return
            for b in buttons:
                b.disabled = True
            try:
                with output:
                    clear_output(wait=True)
                    print("TRÍADE Ω · " + label)
                    result = func()
                    if result is not None:
                        print(json.dumps(result, ensure_ascii=False, indent=2, default=str)[:10000])
            except Exception as exc:
                with output:
                    print("✗ OPERACIÓN DETENIDA:", type(exc).__name__, str(exc)[:1250])
                    print("Bodega y Git no deben modificarse manualmente para saltar el bloqueo.")
            finally:
                for b in buttons:
                    b.disabled = False
                busy.release()
                try: refresh()
                except Exception: pass
        button.on_click(clicked)
        buttons.append(button)
        return button

    def choose():
        if desired.value == "R6.3.1-rc" and approve.value.strip() != "ACTUALIZAR R6.3.1":
            raise RuntimeError("Escribe ACTUALIZAR R6.3.1 para activar candidato no estable")
        set_preference(r5, desired.value)
        return {"version_preferida_guardada_en_drive": desired.value}

    def start():
        preferred = (_json(Path(r5.BASE) / "operacion_colab_r7" / "version_preferida.json") or {}).get("version")
        return boot(r5, chosen=preferred, reporter=print)

    def check_release():
        st = inspect(r5)
        try:
            result = subprocess.run(["git", "-C", str(r5.ROOT), "ls-remote", "origin", "refs/heads/main"],
                                    capture_output=True, text=True, timeout=18, check=True)
            st["github_main_actual"] = result.stdout.split()[0] if result.stdout else "no obtenido"
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            st["github_main_actual"] = "sin confirmar: " + type(exc).__name__
        st["catalogo"] = [{"version": ver,"commit_fijado": sha} for ver,sha in [("R5",R5_SHA),("R6.3.1-rc",R631_BUNDLE)]]
        st["actualizacion_automatica_desde_main"] = False
        return st

    def backup():
        return r5.save_review_copy()

    def force_check():
        return {"drive_guardian_r5": _verify_review(r5), "drive_guardian_r7": _verify_r7(r5),"marca_observada": _highwater(r5),"local": inspect(r5)}

    def manual_candidate():
        if approve.value.strip() != "ACTUALIZAR R6.3.1":
            raise RuntimeError("Confirmación no coincide")
        result = apply_candidate(r5)
        set_preference(r5,"R6.3.1-rc")
        save_state(r5)
        return result

    controls = [
        action("Iniciar / recuperar", start, "235px"),
        action("Verificar versiones", check_release, "210px"),
        action("Examinar memoria", force_check, "205px"),
        action("Guardar elección en Drive", choose, "245px"),
        action("Actualizar R6.3.1", manual_candidate, "220px"),
        action("Auditar workers (30s)", lambda: r5.audit_progress(30), "220px"),
        action("Respaldo verificado", backup, "220px"),
        action("Abrir Tríade React", r5.open_frontend, "215px"),
        action("Actualizar indicadores", refresh, "220px"),
    ]
    display(banner, state, desired, approve, w.Box(controls, layout=w.Layout(display="flex", flex_flow="row wrap", gap="6px")), output)
    refresh()
    return {"refresh":refresh, "output":output}
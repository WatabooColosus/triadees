"""Tríade Ω · reproducible Colab R5 -> R6.3.1 boot continuation.

Run after R5 has restored the user-owned Bodega and started its own API.
The Colab VM is disposable; this script rehydrates pinned code from GitHub.
No secret material, weights, or SQLite snapshots are committed to Git.
"""
from __future__ import annotations
import ast
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import types
import urllib.request
from pathlib import Path

ROOT = Path("/content/Triade")
R5 = "8fdd397b09d7c7da5da8db30235ce626d6a271ec"
R62_LOADER = "d5665af89167e9d246f4093eca6f0d0c62a27f65"
R63_LOADER = "8c8b48d2a31885830c7f522da48bd756e62613e6"
R631_LOADER = "8e0077ada7364384f1b6dcb064b0c29dfb75e18f"
R62_SOURCE = "860351246340913c5095ab85e7087facadb5a21f"
R63_SOURCE = "777dd370dd8b23f5d93303afa7796ceba51166ba"
R631_SOURCE = "70e17c7e3f98b162cddf98a6441830e9802e3e55"
ORIGIN = "https://github.com/WatabooColosus/triadees.git"

def _git(*args, timeout=180):
    result = subprocess.run(["git", "-C", str(ROOT), *args],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode(errors="replace")[-900:])
    return result.stdout

def _loader(name: str, commit: str, path: str):
    _git("fetch", "--no-tags", "--depth", "1", "origin", commit)
    if _git("rev-parse", "FETCH_HEAD").decode().strip() != commit:
        raise RuntimeError("Commit no verificado: " + name)
    data = _git("show", commit + ":" + path)
    if not 0 < len(data) < 220000:
        raise RuntimeError("Módulo inválido: " + name)
    tree = ast.parse(data.decode("utf-8"), filename=path)
    module = types.ModuleType(name)
    exec(compile(tree, path, "exec"), module.__dict__)
    return module

def rehydrate(r5):
    """Run from the same Colab kernel after the original R5 cell finishes."""
    import sqlite3
    print("TRÍADE Ω · CONTINUIDAD GIT R6.3.1")
    if not ROOT.is_dir() or not (ROOT / ".git").is_dir():
        raise RuntimeError("Primero inicia el Colab R5 original")
    if _git("rev-parse", "HEAD").decode().strip() != R5:
        raise RuntimeError("El instalador R5 no coincide; actualización bloqueada")
    if _git("remote", "get-url", "origin").decode().strip() not in (
        ORIGIN, ORIGIN.removesuffix(".git")
    ):
        raise RuntimeError("Git origin no corresponde a Tríade")
    if Path(r5.ROOT).resolve() != ROOT.resolve():
        raise RuntimeError("ROOT de R5 inconsistente")
    db = Path(r5.DB).resolve()
    if db != (ROOT / "triade/memory/triade.db").resolve() or not db.is_file():
        raise RuntimeError("Bodega R5 ausente o ubicación no reconocida")
    r5._owner_account_status(db)
    r5.check_working_identity()
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=20) as c:
        if c.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Bodega inconsistente; no instalar")
        before = {table:c.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                  for table in ("neurons","autonomous_tasks","auth_users")}
    if not all((Path(r5.WORK) / p).is_file()
               for p in ("restore_proof.json","r5_continuity.json")):
        raise RuntimeError("No hay prueba de continuidad de R5; no actualizar")

    r62 = _loader("triade_r62_stable_loader", R62_LOADER,
                  "tools/triade_colab_r62_updater.py")
    r63 = _loader("triade_r63_stable_loader", R63_LOADER,
                  "tools/triade_colab_r63_updater.py")
    hotfix = _loader("triade_r631_safe_patch", R631_LOADER,
                     "tools/triade_r631_apply.py")
    print("✓ Cargadores oficiales fijados a commits verificados")

    # Each updater checks local code hashes, runs tests, takes a SQLite
    # backup, and restarts only the strictly owned R5 API process.
    print("1/3 · Reconstituir R6.2…")
    r62_prepared = r62.prepare(r5)
    if r62_prepared.get("tests") != "pass":
        raise RuntimeError("R6.2 no superó pruebas")
    result62 = r62.apply_and_restart(r5, "ACTUALIZAR R6.2")
    if result62.get("status") not in ("active_candidate","already_installed"):
        raise RuntimeError("R6.2 no acreditada")
    print("✓ R6.2:", result62["status"])

    print("2/3 · Reconstituir R6.3…")
    r63_prepared = r63.prepare(r5)
    if r63_prepared.get("tests") != "pass":
        raise RuntimeError("R6.3 no superó pruebas")
    result63 = r63.apply_and_restart(r5, "ACTUALIZAR R6.3")
    if result63.get("status") not in ("active_candidate","already_installed"):
        raise RuntimeError("R6.3 no acreditada")
    print("✓ R6.3:", result63["status"])

    print("3/3 · Aplicar filtro seguro R6.3.1…")
    hotfix.main()
    code = _git("show", R631_SOURCE + ":triade/neurons/functional_evidence.py")
    live = (ROOT / "triade/neurons/functional_evidence.py").read_bytes()
    if live != code:
        raise RuntimeError("R6.3.1 no coincide con fuente Git verificada")

    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=20) as c:
        if c.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Integridad posterior no acreditada")
        after = {table:c.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                 for table in before}
    if any(after[k] < before[k] for k in before):
        raise RuntimeError("Conteos de identidad/continuidad disminuyeron")
    with urllib.request.urlopen("http://127.0.0.1:8010/health/live",
                                timeout=15) as resp:
        if resp.status != 200:
            raise RuntimeError("API no responde HTTP 200")
    manifest = {
        "status":"rehydrated_candidate",
        "version":"R6.3.1-rc",
        "r5_head":R5,
        "r62_source":R62_SOURCE,
        "r63_source":R63_SOURCE,
        "r631_source":R631_SOURCE,
        "verified_module_sha256":hashlib.sha256(live).hexdigest(),
        "db_replaced":False,
        "db_integrity":"ok",
        "db_counts_before":before,
        "db_counts_after":after,
        "api_http":200,
        "verified_at":dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    local = Path(r5.WORK) / "actualizaciones" / "continuidad_git_r631.json"
    local.parent.mkdir(parents=True, exist_ok=True)
    tmp = local.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),
                   encoding="utf-8")
    os.replace(tmp,local)

    # Small public-code manifest only; never export raw Bodega or backup key.
    drive = Path("/content/drive/MyDrive/Triade/distribucion/releases")
    if Path("/content/drive/MyDrive").is_dir() and os.path.ismount("/content/drive"):
        try:
            drive.mkdir(parents=True, exist_ok=True)
            dst = drive / "continuidad_git_r631.json"
            temp = drive / "continuidad_git_r631.json.tmp"
            temp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),
                            encoding="utf-8")
            os.replace(temp,dst)
            print("✓ Manifiesto de versión escrito en Drive:",dst)
        except OSError as exc:
            print("⚠ Drive sin confirmación de manifiesto:",type(exc).__name__,str(exc)[:200])
    else:
        print("⚠ Drive no montado: versión reproducible desde Git, manifiesto solo local")

    print("✓ API HTTP 200; Bodega íntegra; identidad y conteos preservados")
    print("✓ Código recuperado desde Git. Los servicios solo permanecen mientras Colab siga activo.")
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
    return manifest

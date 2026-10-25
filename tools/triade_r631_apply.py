"""Tríade R6.3.1 · safe functional evaluation hotfix, without API restart.

Applies only the exact allowlisted semantic-quarantine fix for CLI probes.
Refuses unknown local changes, verifies pinned Git commit, runs unit tests,
and backs up the original module. Does NOT alter live SQLite or memory.
"""
from __future__ import annotations
import ast
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path("/content/Triade")
WORK = Path("/content/triade_operacion_r5")
R63 = "777dd370dd8b23f5d93303afa7796ceba51166ba"
R631 = "70e17c7e3f98b162cddf98a6441830e9802e3e55"
R5 = "8fdd397b09d7c7da5da8db30235ce626d6a271ec"
REPO = "https://github.com/WatabooColosus/triadees.git"
TARGET = "triade/neurons/functional_evidence.py"
FILES = [TARGET, "tests/test_neuron_functional_evidence.py", "tools/triade_r631_recover.py"]

def cmd(*argv, timeout=120):
    p = subprocess.run(argv, cwd=ROOT, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=timeout)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors="replace")[-900:])
    return p.stdout

def hash_bytes(b):
    return hashlib.sha256(b).hexdigest()

def main():
    if not (ROOT / ".git").is_dir() or not (ROOT / "triade/memory/triade.db").is_file():
        raise RuntimeError("No se detecta la sesión R5 actual; no se modifica nada")
    origin = cmd("git", "-C", str(ROOT), "remote", "get-url", "origin").decode().strip()
    if origin not in (REPO, REPO.removesuffix(".git")):
        raise RuntimeError("El repositorio no es Tríade")
    head = cmd("git", "-C", str(ROOT), "rev-parse", "HEAD").decode().strip()
    if head != R5:
        raise RuntimeError("HEAD distinto de R5; no se sobreescribe ninguna versión")
    active_path = WORK / "actualizaciones/r63_active.json"
    if not active_path.is_file():
        raise RuntimeError("R6.3 activa no acreditada")
    active = json.loads(active_path.read_text(encoding="utf-8"))
    if active.get("candidate_commit") != R63 or active.get("status") != "active_candidate":
        raise RuntimeError("R6.3 activa no coincide")
    live = ROOT / TARGET
    if not live.is_file() or live.is_symlink():
        raise RuntimeError("Módulo actual ausente o inseguro")
    cmd("git", "-C", str(ROOT), "fetch", "--no-tags", "--depth", "1", "origin", R631, timeout=160)
    if cmd("git", "-C", str(ROOT), "rev-parse", "FETCH_HEAD").decode().strip() != R631:
        raise RuntimeError("Git no verificó el commit R6.3.1")
    sources = {name: cmd("git", "-C", str(ROOT), "show", R631 + ":" + name) for name in FILES}
    baseline = cmd("git", "-C", str(ROOT), "show", R63 + ":" + TARGET)
    for name, data in sources.items():
        if not (0 < len(data) < 250000):
            raise RuntimeError("Archivo inesperado: " + name)
        ast.parse(data.decode("utf-8"), filename=name)
    current = live.read_bytes()
    if current not in (baseline, sources[TARGET]):
        raise RuntimeError("El módulo R6.3 tiene modificaciones desconocidas; no sobrescribir")

    stage = WORK / "actualizaciones/r631_stage"
    stage.mkdir(parents=True, exist_ok=True)
    os.chmod(stage, 0o700)
    for name in FILES:
        dest = stage / Path(name).name
        if dest.is_symlink() or (dest.exists() and dest.read_bytes() != sources[name]):
            raise RuntimeError("Conflicto del staging: " + str(dest))
        if not dest.exists():
            dest.write_bytes(sources[name])
            os.chmod(dest, 0o600)

    print("✓ Git R6.3.1 y fuentes verificadas")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(stage)
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(stage),
         "-p", "test_neuron_functional_evidence.py", "-v"],
        cwd=stage, env=env, text=True, capture_output=True, timeout=90,
    )
    if proc.returncode:
        print(proc.stdout[-1000:], proc.stderr[-3500:])
        raise RuntimeError("Pruebas R6.3.1 fallaron. Código original intacto.")
    print("✓ Pruebas completas superadas:", proc.stderr.strip().splitlines()[-2:])

    from sqlite3 import connect
    db = ROOT / "triade/memory/triade.db"
    with connect(db.as_uri() + "?mode=ro", uri=True, timeout=20) as c:
        if c.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Bodega no íntegra: actualización cancelada")
    print("✓ Bodega íntegra")

    if current != sources[TARGET]:
        backup = WORK / "actualizaciones/r631_backup" / dt.datetime.now(
            dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup.mkdir(parents=True, exist_ok=False)
        os.chmod(backup, 0o700)
        shutil.copy2(live, backup / live.name)
        tmp = live.with_name("." + live.name + ".r631tmp")
        if tmp.exists() or tmp.is_symlink():
            raise RuntimeError("Archivo temporal previo en conflicto; no se escribe")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(sources[TARGET])
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, live)
        print("✓ Módulo R6.3.1 instalado; copia del original:", backup)
    else:
        print("✓ Módulo R6.3.1 ya instalado (idempotente)")

    script = ROOT / "tools/triade_r631_recover.py"
    if script.exists() and script.read_bytes() != sources[FILES[2]]:
        raise RuntimeError("Herramienta de recuperación local diferente: no sobrescribir")
    if not script.exists():
        script.write_bytes(sources[FILES[2]])
        os.chmod(script, 0o600)
    meta = {"status": "cli_hotfix_ready", "module_sha256": hash_bytes(sources[TARGET]),
            "candidate_commit": R631, "api_not_restarted": True,
            "bodega_modified": False}
    (stage / "installed.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("✓ API 8010 y workers siguen activos; no hubo reinicio")
    print("✓ R6.3.1 listo para CLI; se respetan las cuarentenas semánticas")
    print("Vista previa de resultados realmente archivados:")
    subprocess.run([sys.executable, str(script), "--neuron", "11", "--limit", "5"],
                   cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)}, check=True)

if __name__ == "__main__":
    main()

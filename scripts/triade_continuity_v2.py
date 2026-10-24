"""Tríade Ω 5.8: índice de continuidad v2, aislado del publicador legado.

Uso en el MISMO kernel de Colab, con Drive montado:
    %run /content/drive/MyDrive/Triade/TRIADE_CONTINUIDAD_V2_INDEPENDIENTE.py

Invoca run(publish=True) SOLO tras preflight. No restaura, arranca ni detiene
procesos. No sobreescribe active.json de v1 y no toca la Bodega origen.

V2 no declara listo el arranque de Colab: el restaurador/boot también debe
actualizarse explícitamente para usar y verificar este índice.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

GUARD = "wal_closed_and_rows_verified_v2"
LINEAGE = "90e9a51dd7ffef31"
MONOTONE = (
    "neurons", "autonomous_tasks", "neuron_education_sessions",
    "neuron_education_applications", "metabolic_cycle", "auth_users",
    "auth_email_identities", "worker_runs", "governed_research_runs",
)
ROOT = Path("/content/Triade_580_Limpia")
DRIVE = Path("/content/drive/MyDrive/Triade")
STORE = DRIVE / "continuidad_runtime/v2"
INDEX = STORE / "active_verified.json"


def _hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _inspect(path: Path, *, immutable: bool) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    uri = path.resolve().as_uri() + ("?mode=ro&immutable=1" if immutable else "?mode=ro")
    with contextlib.closing(sqlite3.connect(uri, uri=True, timeout=12)) as con:
        if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Bodega o copia SQLite sin integridad")
        journal = str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        tables = {str(x[0]) for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        absent = [name for name in MONOTONE if name not in tables]
        if absent:
            raise RuntimeError("Tablas requeridas ausentes: " + ",".join(absent))
        counts = {t: int(con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]) for t in MONOTONE}
    return {"counts": counts, "journal_mode": journal}


def _coordinator():
    # Import only from the current kernel. This is a pure status/accessor use;
    # any failure stops before creating or overwriting a backup pointer.
    import sys
    c = sys.modules.get("triade_colab_oneclick_runtime")
    if c is None:
        raise RuntimeError("Ejecutar en mismo kernel que tiene el gestor de Tríade")
    if not callable(getattr(c, "inspect_db", None)):
        raise RuntimeError("Gestor sin verificador de identidad")
    if Path(c.DB).resolve() != (ROOT / "triade/memory/triade.db").resolve():
        raise RuntimeError("Ruta de Bodega inesperada; no publicar")
    return c


def _identity(coordinator: Any, path: Path) -> dict[str, Any]:
    info = coordinator.inspect_db(path)
    if info.get("integrity") != "ok" or info.get("lineage") != LINEAGE:
        raise RuntimeError("Integridad/linaje de Tríade no comprobados")
    if (info.get("counts") or {}).get("auth_users") != 1:
        raise RuntimeError("No hay un único propietario confirmado")
    return info


def _check_no_regression(new: dict[str, int], old: dict[str, int], *, label: str) -> None:
    for name in MONOTONE:
        if int(new[name]) < int(old[name]):
            raise RuntimeError(f"REGRESION {label}: {name} {old[name]} -> {new[name]}")


def _validate_pointer(coordinator: Any, pointer: Path) -> dict[str, Any]:
    data = json.loads(pointer.read_text(encoding="utf-8"))
    if (data.get("guard") != GUARD or data.get("lineage") != LINEAGE or
            data.get("schema") != "triade_verified_continuity_v2"):
        raise RuntimeError("Puntero v2 sin contrato protegido")
    name = data.get("file")
    if not isinstance(name, str) or name != Path(name).name or not name.endswith(".sqlite3"):
        raise RuntimeError("Nombre de imagen v2 inseguro")
    image = pointer.parent / name
    sidecar = image.with_suffix(".json")
    if not image.is_file() or not sidecar.is_file():
        raise RuntimeError("Archivos de v2 faltantes")
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    if (meta.get("kind") != "sqlite_wal_closed_verified" or
            meta.get("guard") != GUARD or meta.get("sha256") != data.get("sha256") or
            int(meta.get("size", -1)) != image.stat().st_size or
            _hash(image) != data.get("sha256")):
        raise RuntimeError("Imagen v2 sin checksum o sidecar coherente")
    if image.with_name(image.name + "-wal").exists():
        raise RuntimeError("WAL sin cerrar dentro de v2")
    check = _inspect(image, immutable=True)
    if check["journal_mode"] != "delete":
        raise RuntimeError("Imagen v2 no consolidada a journal DELETE")
    info = _identity(coordinator, image)
    if check["counts"] != data.get("counts") or info["counts"] != data.get("counts"):
        raise RuntimeError("Índice v2 y archivo no coinciden")
    if meta.get("verified_image_counts") != data.get("counts"):
        raise RuntimeError("Metadatos v2 y archivo no coinciden")
    return {"file": name, "sha256": data["sha256"], "counts": check["counts"], "bytes": image.stat().st_size}


def run(*, publish: bool = False) -> dict[str, Any]:
    c = _coordinator()
    if not DRIVE.is_dir():
        raise RuntimeError("Google Drive no está montado")
    live = _identity(c, Path(c.DB))
    live_counts = _inspect(Path(c.DB), immutable=False)["counts"]
    if live_counts != live["counts"]:
        raise RuntimeError("Bodega cambió durante preflight; repetir después")
    previous = _validate_pointer(c, INDEX) if INDEX.is_file() else None
    if previous:
        _check_no_regression(live_counts, previous["counts"], label="v2->Bodega")
    preliminary = {"status": "preflight_only", "lineage": LINEAGE,
                   "live_counts": live_counts, "prior_v2": previous,
                   "legacy_active_trusted": False,
                   "modifies_live_bodega": False}
    if not publish:
        print(json.dumps(preliminary, ensure_ascii=False, indent=2))
        return preliminary

    # Only v2 consumes this lock: old v1 writer cannot corrupt v2 index.
    STORE.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (STORE / ".publisher.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Recheck after obtaining the interprocess v2 publisher lock.
        previous = _validate_pointer(c, INDEX) if INDEX.is_file() else None
        with tempfile.TemporaryDirectory(prefix="triade-v2-", dir=ROOT) as folder:
            image = Path(folder) / "backup.sqlite3"
            with (contextlib.closing(sqlite3.connect(Path(c.DB).resolve().as_uri() + "?mode=ro", uri=True, timeout=45)) as src,
                  contextlib.closing(sqlite3.connect(image, timeout=45)) as dst):
                src.backup(dst, pages=256, sleep=0.1)
                checkpoint = dst.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if checkpoint is not None and int(checkpoint[0]) != 0:
                    raise RuntimeError("Checkpoint de copia no completado")
                mode = dst.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
                if str(mode).lower() != "delete":
                    raise RuntimeError("No se cerró WAL de imagen")
            observed = _inspect(image, immutable=True)
            validated = _identity(c, image)
            if observed["journal_mode"] != "delete" or observed["counts"] != validated["counts"]:
                raise RuntimeError("Copia inconsistente")
            _check_no_regression(observed["counts"], live_counts, label="origen->imagen")
            if previous:
                _check_no_regression(observed["counts"], previous["counts"], label="v2->imagen")
            if shutil.disk_usage(STORE).free < 2 * image.stat().st_size:
                raise OSError("Drive no dispone de espacio suficiente")
            stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
            filename = f"memoria-verificada-v2-{stamp}.sqlite3"
            staged = STORE / ("." + filename + ".partial")
            final = STORE / filename
            if staged.exists() or final.exists():
                raise RuntimeError("Archivo v2 ya existe")
            try:
                shutil.copyfile(image, staged)
                checksum = _hash(image)
                if _hash(staged) != checksum:
                    raise RuntimeError("Copia Drive no coincide")
                if _inspect(staged, immutable=True) != observed or _identity(c, staged)["counts"] != observed["counts"]:
                    raise RuntimeError("Contenido Drive no coincide")
                os.replace(staged, final)
                manifest = {
                    "schema": "triade_verified_continuity_v2", "guard": GUARD,
                    "file": filename, "lineage": LINEAGE, "sha256": checksum,
                    "counts": observed["counts"], "created_at": dt.datetime.now(dt.UTC).isoformat(),
                    "external_memory_included": False,
                    "not_complete_external_memory_restore": True,
                }
                meta = {"kind": "sqlite_wal_closed_verified", "guard": GUARD,
                        "sha256": checksum, "size": final.stat().st_size,
                        "verified_image_counts": observed["counts"]}
                _atomic_json(final.with_suffix(".json"), meta)
                # Verify all image bytes and rows *before* the pointer moves.
                _validate_candidate(c, manifest, final, meta)
                _atomic_json(INDEX, manifest)
                _validate_pointer(c, INDEX)
                print(json.dumps({"status": "published_v2_verified", "file": filename,
                                  "counts": observed["counts"], "v1_untouched": True},
                                 ensure_ascii=False, indent=2))
                return {"status": "published_v2_verified", "file": filename,
                        "counts": observed["counts"], "v1_untouched": True}
            finally:
                staged.unlink(missing_ok=True)


def _validate_candidate(c: Any, manifest: dict[str, Any], path: Path, meta: dict[str, Any]):
    if not path.is_file() or path.with_name(path.name + "-wal").exists():
        raise RuntimeError("Imagen candidata v2 no cerrada")
    if (meta["sha256"] != _hash(path) or meta["size"] != path.stat().st_size or
            manifest["counts"] != _inspect(path, immutable=True)["counts"] or
            manifest["counts"] != _identity(c, path)["counts"]):
        raise RuntimeError("Imagen candidata v2 no validable")


def _atomic_json(path: Path, document: dict[str, Any]):
    temp = path.with_name("." + path.name + ".partial")
    if temp.exists():
        raise RuntimeError("Existe un publicador paralelo en v2")
    try:
        with temp.open("x", encoding="utf-8") as out:
            json.dump(document, out, ensure_ascii=False, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


if __name__ == "__main__":
    # No mutation, even of Drive, unless explicitly invoked as run(publish=True)
    run(publish=False)

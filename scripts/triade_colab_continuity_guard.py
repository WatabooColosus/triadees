"""Tríade Ω — reparación verificable del respaldo de continuidad en Colab.

Protege el proceso que ya corre, sin parar la API ni tocar la DB origen.
Se instala en el coordinador en memoria y crea una copia SQLite WAL-safe,
auditada contra Bodega, index anterior e imagen publicada en Drive.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import functools
import importlib
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

# Counters that must never go backwards without explicit forensic review.
MONOTONE = (
    "neurons",
    "autonomous_tasks",
    "neuron_education_sessions",
    "neuron_education_applications",
    "metabolic_cycle",
    "auth_users",
    "auth_email_identities",
    "worker_runs",
    "governed_research_runs",
)


def _reject_regression(now: dict[str, Any], before: dict[str, Any], label: str) -> None:
    for name in MONOTONE:
        recent, previous = now.get(name), before.get(name)
        if isinstance(recent, int) and isinstance(previous, int) and recent < previous:
            raise RuntimeError(
                f"CONTINUIDAD_PROTEGIDA: {label}: {name} "
                f"{previous} -> {recent}; ningún índice sustituido"
            )


def _assert_matching_image(a: dict[str, Any], b: dict[str, Any], stage: str) -> None:
    if a.get("lineage") != b.get("lineage"):
        raise RuntimeError(f"CONTINUIDAD_PROTEGIDA: identidad distinta en {stage}")
    if a.get("integrity") != "ok" or b.get("integrity") != "ok":
        raise RuntimeError(f"CONTINUIDAD_PROTEGIDA: SQLite corrupta en {stage}")
    for name, expected in a.get("counts", {}).items():
        got = b.get("counts", {}).get(name)
        if got != expected:
            raise RuntimeError(
                f"CONTINUIDAD_PROTEGIDA: {stage}: {name} "
                f"esperado={expected} observado={got}; publicación bloqueada"
            )


def _image_from_live_sqlite(db: Path, image: Path) -> None:
    """SQLite online backup. Force rollback journal on DESTINATION, then close.

    sqlite3.backup() can inherit WAL mode from the source. Copying just the
    destination's main file while its new WAL contains committed pages is unsafe.
    A brand-new uniquely named image plus explicit checkpoint+DELETE closes
    that loophole. An existing persistent intermediate file is NEVER reused.
    """
    if image.exists() or image.with_name(image.name + "-wal").exists():
        raise FileExistsError("CONTINUIDAD_PROTEGIDA: destino temporal reutilizado")
    with (
        contextlib.closing(
            sqlite3.connect(
                "file:" + str(db.resolve()) + "?mode=ro", uri=True, timeout=30
            )
        ) as source,
        contextlib.closing(sqlite3.connect(image, timeout=30)) as copy,
    ):
        source.backup(copy, pages=256, sleep=0.1)
        checkpoint = copy.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint is not None and checkpoint[0] != 0:
            raise RuntimeError("CONTINUIDAD_PROTEGIDA: checkpoint de copia ocupado")
        mode = copy.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
        if str(mode).lower() != "delete":
            raise RuntimeError("CONTINUIDAD_PROTEGIDA: journal_mode no consolidado")
        if copy.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("CONTINUIDAD_PROTEGIDA: integridad de imagen")
    if image.with_name(image.name + "-wal").exists():
        raise RuntimeError("CONTINUIDAD_PROTEGIDA: WAL no cerrado en copia")


def _archive_old_index(index: Path, store: Path) -> None:
    if not index.is_file():
        return
    archive_dir = store / "index_history_guarded"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
    dest = archive_dir / ("active-before-" + stamp + ".json")
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        content = index.read_bytes()
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if dest.read_bytes() != content:
            raise OSError("El índice histórico no se archivó correctamente")
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


def safe_snapshot(coordinator: Any, *, force: bool = False) -> dict[str, Any]:
    """Publish a verified, strictly non-regressing live image, with no DB writes."""
    if not coordinator.DRIVE.is_dir():
        raise RuntimeError("Drive no disponible")
    live = coordinator.inspect_db(coordinator.DB)
    if live["integrity"] != "ok" or (live["counts"].get("auth_users") or 0) != 1:
        raise RuntimeError("SQLite/identidad de Bodega no certificable")
    existing = None
    if coordinator.INDEX.is_file():
        existing = json.loads(coordinator.INDEX.read_text(encoding="utf-8"))
        if existing.get("lineage") != live["lineage"]:
            raise RuntimeError("Identidad distinta: no se actualiza ningún respaldo")
        _reject_regression(live["counts"], existing.get("counts", {}), "origen-index")
    coordinator.engine.STATE.mkdir(parents=True, exist_ok=True)
    coordinator.STORE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="triade-continuidad-protegida-", dir=coordinator.engine.STATE
    ) as scratch:
        image = Path(scratch) / "imagen-completa.sqlite3"
        _image_from_live_sqlite(coordinator.DB, image)
        saved = coordinator.inspect_db(image)
        if saved.get("lineage") != live.get("lineage"):
            raise RuntimeError("Identidad alterada al respaldar")
        _reject_regression(saved["counts"], live["counts"], "copia-origen")
        if existing:
            _reject_regression(
                saved["counts"], existing.get("counts", {}), "copia-index"
            )
        checksum = coordinator.digest(image)
        if existing and not force and checksum == existing.get("sha256"):
            expected = existing.get("counts", {})
            if all(saved["counts"].get(k) == v for k, v in expected.items()):
                return {"status": "unchanged", "file": existing.get("file")}
        if shutil.disk_usage(coordinator.STORE).free < 2 * image.stat().st_size:
            raise OSError("Espacio insuficiente en Drive; no se publica el índice")
        name = (
            "memoria-guardada-"
            + dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
            + ".sqlite3"
        )
        dest = coordinator.STORE / name
        staging = coordinator.STORE / ("." + name + ".partial")
        if dest.exists() or staging.exists():
            raise FileExistsError("Nombre de respaldo ya ocupado; no se reemplaza")
        try:
            shutil.copyfile(image, staging)
            if coordinator.digest(staging) != checksum:
                raise OSError("SHA256 de copia remota no coincide")
            uploaded = coordinator.inspect_db(staging)
            _assert_matching_image(saved, uploaded, "imagen-en-Drive")
            os.replace(staging, dest)
            if coordinator.digest(dest) != checksum:
                raise OSError("Imagen final en Drive no coincide")
            uploaded = coordinator.inspect_db(dest)
            _assert_matching_image(saved, uploaded, "archivo-final")
            moment = dt.datetime.now(dt.UTC).isoformat()
            metadata = {
                "sha256": checksum,
                "size": dest.stat().st_size,
                "created_at": moment,
                "kind": "sqlite_wal_closed_verified",
                "source_git": coordinator.engine.repo_status(),
                "not_a_complete_external_memory_restore": True,
                "verified_image_counts": saved["counts"],
            }
            coordinator.atomic_json(dest.with_suffix(".json"), metadata)
            # Validate full bytes, image counts and SHA before publishing the
            # pointer. A correctly signed/hashed WRONG image is still wrong.
            verified = coordinator.validated_snapshot(dest)
            if verified is None:
                raise RuntimeError("Copia final no supera el validador histórico")
            _assert_matching_image(saved, verified["info"], "validador-final")
            _archive_old_index(coordinator.INDEX, coordinator.STORE)
            manifest = {
                "file": name,
                "sha256": checksum,
                "lineage": saved["lineage"],
                "counts": saved["counts"],
                "created_at": moment,
                "source_git": metadata["source_git"],
                "external_memory_included": False,
                "guard": "wal_closed_and_rows_verified_v1",
            }
            coordinator.atomic_json(coordinator.INDEX, manifest)
            assert coordinator.INDEX.is_file()
            check_index = json.loads(coordinator.INDEX.read_text(encoding="utf-8"))
            if (
                check_index.get("sha256") != checksum
                or check_index.get("counts") != saved["counts"]
            ):
                raise RuntimeError("Índice protegido no supera lectura posterior")
            return {
                "status": "saved",
                "file": name,
                "counts": saved["counts"],
                "sha256_prefix": checksum[:12],
                "lineage": saved["lineage"],
                "previous_index_archived": existing is not None,
            }
        finally:
            staging.unlink(missing_ok=True)


def install(*, publish_one: bool = True) -> dict[str, Any]:
    """Hot-fix existing notebook runtime. Persists only for this Colab kernel."""
    coordinator = importlib.import_module("triade_colab_oneclick_runtime")
    original = coordinator.snapshot_once
    if getattr(original, "_triade_verified_continuity", False):
        print("Guardián WAL ya instalado; se conserva la versión en memoria.")
        replacement = original
    else:

        @functools.wraps(original)
        def replacement(*, force: bool = False) -> dict[str, Any]:
            with coordinator.BACKUP_MUTEX:
                return safe_snapshot(coordinator, force=force)

        replacement._triade_verified_continuity = True
        coordinator.snapshot_once = replacement
        print("Guardián de continuidad activo para respaldos manuales y periódicos.")
    if publish_one:
        outcome = replacement(force=True)
        print("Copia WAL-safe comprobada:", json.dumps(outcome, ensure_ascii=False))
        return outcome
    return {"status": "guard_installed"}


if __name__ == "__main__":
    install(publish_one=True)

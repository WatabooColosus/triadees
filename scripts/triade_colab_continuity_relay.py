"""Tríade Ω — single-writer handover for Colab continuity (same live kernel).

Stops ONLY stale TriadeContinuitySaver threads. Fences legacy active.json
publishers, installs verified WAL-safe snapshot_once and starts one new
periodic saver. Does not restart the API, change runtime mode, decrypt keys,
or restore any SQLite image. If an old saver cannot stop, fails closed.
"""

from __future__ import annotations

import functools
import importlib
import importlib.util
import json
import sys
import threading
from pathlib import Path
from typing import Any

GUARD = Path("/content/drive/MyDrive/Triade/TRIADE_GUARDIAN_CONTINUIDAD.py")
EXPECTED_LINEAGE = "90e9a51dd7ffef31"
SAVER_NAME = "TriadeContinuitySaver"
GUARD_VERSION = "wal_closed_and_rows_verified_v1"


def _savers() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.is_alive() and t.name == SAVER_NAME]


def _source_globals(thread: threading.Thread) -> dict[str, Any]:
    target = getattr(thread, "_target", None)
    namespace = getattr(target, "__globals__", None)
    if not isinstance(namespace, dict):
        raise TypeError("CONTINUIDAD_PROTEGIDA: hilo antiguo no inspeccionable")
    if not {"STOP", "snapshot_once", "atomic_json"}.issubset(namespace):
        raise RuntimeError("CONTINUIDAD_PROTEGIDA: escritor desconocido; no se detiene")
    stop = namespace["STOP"]
    if not all(callable(getattr(stop, attr, None)) for attr in ("set", "wait")):
        raise RuntimeError("CONTINUIDAD_PROTEGIDA: señal STOP desconocida")
    return namespace


def _fence_legacy_index(namespace: dict[str, Any], index: Path) -> None:
    """A stale UI/callback may still invoke a cached legacy snapshot function."""
    old = namespace["atomic_json"]
    if getattr(old, "_triade_index_fenced", False):
        return

    @functools.wraps(old)
    def fenced(path: str | Path, payload: dict[str, Any]) -> Any:
        if Path(path).resolve() == index.resolve() and (
            not isinstance(payload, dict) or payload.get("guard") != GUARD_VERSION
        ):
            raise RuntimeError(
                "CONTINUIDAD_PROTEGIDA: escritura de índice por escritor "
                "anterior bloqueada; los snapshots previos siguen intactos"
            )
        return old(path, payload)

    fenced._triade_index_fenced = True
    namespace["atomic_json"] = fenced


def _load_guard() -> Any:
    if not GUARD.is_file():
        raise FileNotFoundError(f"No se encuentra el guardián en {GUARD}")
    name = "_triade_guardian_single_writer_v1"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, GUARD)
    if spec is None or spec.loader is None:
        raise RuntimeError("Módulo guardián no cargable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    if not callable(getattr(module, "install", None)) or not callable(
        getattr(module, "safe_snapshot", None)
    ):
        raise TypeError("Módulo guardián sin instalación segura")
    return module


def execute() -> dict[str, Any]:
    # All preflight checks are read-only. No restoration and no new identity.
    coordinator = importlib.import_module("triade_colab_oneclick_runtime")
    guard = _load_guard()
    db = coordinator.inspect_db(coordinator.DB)
    if db.get("integrity") != "ok" or db.get("lineage") != EXPECTED_LINEAGE:
        raise RuntimeError("CONTINUIDAD_PROTEGIDA: identidad/Bodega activa no coincide")
    if int(db.get("counts", {}).get("auth_users") or 0) != 1:
        raise RuntimeError("CONTINUIDAD_PROTEGIDA: propietario único no acreditado")
    index = coordinator.INDEX
    if not index.is_file():
        raise RuntimeError("CONTINUIDAD_PROTEGIDA: no hay índice de continuidad")
    old_index = json.loads(index.read_text(encoding="utf-8"))
    if old_index.get("lineage") != EXPECTED_LINEAGE:
        raise RuntimeError("CONTINUIDAD_PROTEGIDA: índice de otra identidad")
    for table, old_value in (old_index.get("counts") or {}).items():
        now_value = db.get("counts", {}).get(table)
        if (
            isinstance(old_value, int)
            and isinstance(now_value, int)
            and now_value < old_value
        ):
            raise RuntimeError(
                f"CONTINUIDAD_PROTEGIDA: Bodega actual regresó en {table}; "
                "no se cambia nada"
            )

    old_threads = _savers()
    namespaces: list[dict[str, Any]] = []
    for thread in old_threads:
        ns = _source_globals(thread)
        if all(ns is not seen for seen in namespaces):
            namespaces.append(ns)
    if all(coordinator.__dict__ is not ns for ns in namespaces):
        namespaces.append(coordinator.__dict__)

    # First fence active.json: protects UI callbacks that captured an old
    # snapshot function. Stop only continuity savers; DO NOT stop Triade workers.
    for ns in namespaces:
        _fence_legacy_index(ns, index)
    for thread in old_threads:
        _source_globals(thread)["STOP"].set()
    for thread in old_threads:
        thread.join(timeout=45)
    survivors = _savers()
    if survivors:
        raise RuntimeError(
            "CONTINUIDAD_PROTEGIDA: el guardado antiguo sigue vivo; "
            "sin publicar otra copia ni iniciar un segundo escritor"
        )

    # Install verified writer, including stale notebook namespaces, so any
    # old UI button/old callback routes to the canonical safe implementation.
    guard.install(publish_one=False)
    protected = coordinator.snapshot_once
    if not getattr(protected, "_triade_verified_continuity", False):
        raise RuntimeError("CONTINUIDAD_PROTEGIDA: instalación no comprobable")
    for ns in namespaces:
        ns["snapshot_once"] = protected
        # Former notebook namespaces may still serve UI callbacks. Re-point
        # their saver entrypoint at the ONE current manager, not a second timer.
        if ns is not coordinator.__dict__:
            ns["background_saver"] = coordinator.background_saver

    outcome = protected(force=True)
    if outcome.get("status") not in {"saved", "unchanged"}:
        raise RuntimeError("CONTINUIDAD_PROTEGIDA: no se confirmó nueva copia")
    published = json.loads(index.read_text(encoding="utf-8"))
    if (
        published.get("lineage") != EXPECTED_LINEAGE
        or published.get("guard") != GUARD_VERSION
    ):
        raise RuntimeError("CONTINUIDAD_PROTEGIDA: índice final no protegido")
    if (
        published.get("counts")
        != coordinator.inspect_db(coordinator.STORE / published["file"])["counts"]
    ):
        raise RuntimeError("CONTINUIDAD_PROTEGIDA: índice e imagen no coinciden")

    # Reuse the original coordinator's timer. It now resolves the guarded
    # snapshot_once through its own globals, and there are no old timer threads.
    start = coordinator.background_saver()
    after = _savers()
    if len(after) != 1 or start.get("status") not in {"running", "already_running"}:
        raise RuntimeError("CONTINUIDAD_PROTEGIDA: no hay exactamente un guardador")
    if getattr(coordinator, "THREAD", None) is not after[0]:
        raise RuntimeError(
            "CONTINUIDAD_PROTEGIDA: hilo periódico no pertenece al gestor"
        )
    result = {
        "status": "single_guarded_writer",
        "identity": EXPECTED_LINEAGE,
        "legacy_savers_stopped": len(old_threads),
        "active_savers": len(after),
        "periodic_interval_seconds": coordinator.SNAP_INTERVAL_SECONDS,
        "snapshot": outcome,
        "active_index_guard": published["guard"],
        "restarted_api": False,
        "restarted_workers": False,
        "deleted_archives": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    execute()

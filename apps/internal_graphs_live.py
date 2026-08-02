"""Lectura viva y no destructiva de los grafos internos de Tríade Ω."""
from __future__ import annotations

import json
import os
import resource
import shutil
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

from triade.observability.file_graph import build_file_graph
from triade.observability.neural_graph import build_neural_graph

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "triade" / "memory" / "triade.db"


def _db_path() -> Path:
    value = os.getenv("TRIADE_DB_PATH", str(DEFAULT_DB))
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _resource_snapshot() -> dict[str, Any]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    disk = shutil.disk_usage(ROOT)
    load = list(os.getloadavg()) if hasattr(os, "getloadavg") else []
    return {
        "pid": os.getpid(),
        "process_cpu_seconds": round(usage.ru_utime + usage.ru_stime, 4),
        "process_max_rss_kb": int(usage.ru_maxrss),
        "load_average": load,
        "disk_total": disk.total,
        "disk_used": disk.used,
        "disk_free": disk.free,
    }


def _database_health(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": "unavailable", "integrity": "unknown"}
    result: dict[str, Any] = {
        "exists": True,
        "path": "protected",
        "size": path.stat().st_size,
        "integrity": "unknown",
        "tables": 0,
    }
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
    try:
        result["integrity"] = connection.execute("PRAGMA quick_check").fetchone()[0]
        result["tables"] = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
    finally:
        connection.close()
    return result


def build_live_snapshot(*, file_limit: int | None = None, neural_limit: int = 5000) -> dict[str, Any]:
    """Construye un snapshot únicamente desde filesystem, SQLite y proceso reales."""
    file_nodes, file_edges = build_file_graph(ROOT)
    if file_limit is not None:
        allowed = {node.node_id for node in file_nodes[:file_limit]}
        file_nodes = file_nodes[:file_limit]
        file_edges = [edge for edge in file_edges if edge.source in allowed and edge.target in allowed]
    db_path = _db_path()
    neural_nodes, neural_edges = build_neural_graph(db_path, limit=neural_limit)
    return {
        "schema_version": 2,
        "generated_at": time.time(),
        "source": {
            "filesystem": str(ROOT.name),
            "database": "sqlite-read-only",
            "runtime": "current-python-process",
            "simulated": False,
        },
        "physical": {
            "nodes": [asdict(node) for node in file_nodes],
            "edges": [asdict(edge) for edge in file_edges],
        },
        "neural": {
            "nodes": [asdict(node) for node in neural_nodes],
            "edges": [asdict(edge) for edge in neural_edges],
        },
        "resources": _resource_snapshot(),
        "database": _database_health(db_path),
    }


def event_stream(interval_seconds: float = 2.0) -> Iterator[str]:
    """Entrega snapshots SSE; una desconexión del cliente termina el generador."""
    while True:
        try:
            payload = build_live_snapshot()
            yield f"event: snapshot\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
        except (OSError, sqlite3.Error, ValueError) as exc:
            error = {"simulated": False, "error": type(exc).__name__, "detail": str(exc)}
            yield f"event: graph_error\ndata: {json.dumps(error, ensure_ascii=False)}\n\n"
        time.sleep(max(1.0, interval_seconds))

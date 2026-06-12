"""Registro centralizado de errores internos — Tríade Ω.

Reemplaza `except Exception: pass` con registro auditable en worker_events.
Cada error se guarda con scope, run_ref, task_id, payload y traceback truncado.
"""

from __future__ import annotations

import json
import os
import sqlite3
import traceback
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now


ERROR_SEVERITY_POLICY: dict[str, str] = {
    "critical": "Riesgo de corrupción de identidad, memoria estable o seguridad.",
    "error": "Fallo interno recuperable que afecta una tarea o ciclo.",
    "warning": "Degradación controlada sin pérdida de trazabilidad.",
    "info": "Evento diagnóstico no bloqueante.",
}


def record_internal_error(
    scope: str,
    error: Exception | str,
    run_id: str | None = None,
    task_id: int | None = None,
    payload: dict[str, Any] | None = None,
    db_path: str | Path = "triade/memory/triade.db",
    severity: str | None = None,
) -> int | None:
    """Registra un error interno en worker_events para trazabilidad.

    Args:
        scope: módulo/fuente del error (ej: "runner", "mission_planner", "life_pulse")
        error: excepción o string del error
        run_id: run_ref relacionado si existe
        task_id: task_id de worker_tasks si existe
        payload: contexto adicional del error
        db_path: ruta a la base de datos

    Returns:
        ID del evento creado, o None si falla el registro
    """
    db_path = Path(db_path)
    error_str = str(error)
    tb_str = ""
    if isinstance(error, BaseException):
        tb_str = "".join(traceback.format_exception(type(error), error, error.__traceback__))[-2000:]

    event_payload = {
        "error_type": type(error).__name__ if isinstance(error, BaseException) else "string",
        "error_message": error_str[:1000],
        "traceback": tb_str,
        "scope": scope,
        "severity": _normalize_severity(severity, scope, error_str),
        "severity_policy": ERROR_SEVERITY_POLICY,
    }
    if payload:
        event_payload["context"] = payload

    try:
        with _connect(db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO worker_events
                (run_ref, task_id, task_type, event_type, status, message, payload_json, created_at)
                VALUES (?, ?, ?, 'internal_error', 'error', ?, ?, ?)""",
                (
                    run_id,
                    task_id,
                    scope,
                    f"[{scope}] {error_str[:200]}",
                    json.dumps(event_payload, ensure_ascii=False)[:4000],
                    utc_now(),
                ),
            )
            prune_worker_events(conn)
            return int(cursor.lastrowid)
    except Exception:
        return None


def query_internal_errors(
    scope: str | None = None,
    run_id: str | None = None,
    limit: int = 50,
    db_path: str | Path = "triade/memory/triade.db",
) -> list[dict[str, Any]]:
    """Consulta errores internos registrados."""
    db_path = Path(db_path)
    try:
        with _connect(db_path) as conn:
            if scope:
                rows = conn.execute(
                    """SELECT id, run_ref, task_id, task_type, status, message, payload_json, created_at
                    FROM worker_events
                    WHERE event_type = 'internal_error' AND task_type = ?
                    ORDER BY id DESC LIMIT ?""",
                    (scope, limit),
                ).fetchall()
            elif run_id:
                rows = conn.execute(
                    """SELECT id, run_ref, task_id, task_type, status, message, payload_json, created_at
                    FROM worker_events
                    WHERE event_type = 'internal_error' AND run_ref = ?
                    ORDER BY id DESC LIMIT ?""",
                    (run_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT id, run_ref, task_id, task_type, status, message, payload_json, created_at
                    FROM worker_events
                    WHERE event_type = 'internal_error'
                    ORDER BY id DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
            return [_row_to_dict(r) for r in rows]
    except Exception:
        return []


def prune_worker_events(conn: sqlite3.Connection, keep_limit: int | None = None) -> int:
    """Retiene solo los eventos worker más recientes para crecimiento acotado.

    Default: `TRIADE_WORKER_EVENTS_RETENTION` o 5000. Valores <= 0 desactivan
    pruning. Se conservan siempre los últimos N por id.
    """
    if keep_limit is None:
        try:
            keep_limit = int(os.environ.get("TRIADE_WORKER_EVENTS_RETENTION", "5000") or "5000")
        except ValueError:
            keep_limit = 5000
    if keep_limit <= 0:
        return 0
    cursor = conn.execute(
        """
        DELETE FROM worker_events
        WHERE id NOT IN (
            SELECT id FROM worker_events ORDER BY id DESC LIMIT ?
        )
        """,
        (keep_limit,),
    )
    return int(cursor.rowcount or 0)


def _normalize_severity(severity: str | None, scope: str, message: str) -> str:
    if severity:
        clean = severity.strip().lower()
        if clean in ERROR_SEVERITY_POLICY:
            return clean
    lowered = f"{scope} {message}".lower()
    if any(flag in lowered for flag in ("identity_core", "stable memory", "memoria estable", "safety")):
        return "critical"
    if any(flag in lowered for flag in ("degraded", "fallback", "timeout")):
        return "warning"
    return "error"


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    payload_raw = d.get("payload_json")
    if payload_raw:
        try:
            d["payload"] = json.loads(payload_raw)
        except (json.JSONDecodeError, TypeError):
            d["payload"] = {"raw": str(payload_raw)[:500]}
    d.pop("payload_json", None)
    return d


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

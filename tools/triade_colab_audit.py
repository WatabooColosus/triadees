"""Read-only Colab audit; schema-aware counters, no synthetic runtime evidence."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from triade.db import sqlite3

COUNTERS = {
    "worker_events": "id",
    "worker_runs": "id",
    "metabolic_cycle": "cycle_id",
    "runtime_health_snapshots": "snapshot_id",
    "neuron_education_sessions": None,
    "neuron_education_applications": None,
    "neuron_activity": None,
}
ENV_KEYS = (
    "TRIADE_SLOW_FULL_LOCAL",
    "TRIADE_ALWAYS_ON_MODE",
    "TRIADE_DISABLE_BACKGROUND",
    "TRIADE_WORKERS_ALWAYS_ON",
    "TRIADE_WORKERS_AUTOSTART",
    "TRIADE_CONTINUOUS_RUNNER",
    "TRIADE_CONTINUOUS_AUTONOMY_LEVEL",
)


def _columns(conn, table):
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


def snapshot(db):
    """Missing columns are explicit; never let SQLite quote them as strings."""
    out, errors = {}, {}
    with contextlib.closing(
        sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    ) as conn:
        for table, key in COUNTERS.items():
            columns = _columns(conn, table)
            if not columns:
                out[table] = None
                errors[table] = "table_missing"
                continue
            # Counts remain meaningful for text identifiers, which cannot be subtracted.
            out[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if key and key not in columns:
                errors[table] = f"column_missing:{key}; using row count"
        for table in ("autonomous_tasks", "worker_tasks"):
            if "status" in _columns(conn, table):
                out[table + "_statuses"] = dict(
                    conn.execute(
                        f'SELECT status, COUNT(*) FROM "{table}" GROUP BY status'
                    )
                )
        columns = _columns(conn, "worker_events")
        out["event_cursor"] = (
            conn.execute("SELECT COALESCE(MAX(id),0) FROM worker_events").fetchone()[0]
            if "id" in columns
            else None
        )
    return out, errors


def details(db, cursor):
    """Only structural fields, never task contents, tokens, messages or payloads."""
    result = {}
    with contextlib.closing(
        sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    ) as conn:
        conn.row_factory = sqlite3.Row
        specs = {
            "worker_events": (
                "id",
                "task_id",
                "task_type",
                "event_type",
                "status",
                "created_at",
            ),
            "worker_tasks": (
                "id",
                "task_type",
                "status",
                "safety_status",
                "created_at",
                "started_at",
                "finished_at",
            ),
            "autonomous_tasks": (
                "id",
                "task_type",
                "status",
                "created_at",
                "started_at",
                "finished_at",
            ),
        }
        for table, allowed in specs.items():
            columns = _columns(conn, table)
            selected = [name for name in allowed if name in columns]
            if not selected:
                continue
            fields = ", ".join(f'"{name}"' for name in selected)
            where, params = "", ()
            if table == "worker_events" and type(cursor) is int and "id" in columns:
                where, params = " WHERE id > ?", (cursor,)
            elif "status" in columns and table != "worker_events":
                where = " WHERE status IN ('pending','running','blocked','failed','retry','queued')"
            order = ' ORDER BY "id" DESC' if "id" in columns else ""
            result[table] = [
                dict(row)
                for row in conn.execute(
                    f'SELECT {fields} FROM "{table}"' + where + order + " LIMIT 25",
                    params,
                )
            ]
    return result


def effective_config(work):
    """Read only allowlisted environment of the registered, still matching API."""
    try:
        record = json.loads((Path(work) / "api_ownership.json").read_text())
        pid = int(record["pid"])
        cmd = (Path("/proc") / str(pid) / "cmdline").read_bytes()
        if b"apps.single_port_app:app" not in cmd:
            return {"status": "registered_pid_not_api"}
        env = dict(
            item.split(b"=", 1)
            for item in (Path("/proc") / str(pid) / "environ").read_bytes().split(b"\0")
            if b"=" in item
        )
        return {
            "status": "observed",
            "pid": pid,
            "values": {
                key: env[key.encode()].decode(errors="replace")
                for key in ENV_KEYS
                if key.encode() in env
            },
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "not_observed"}


def endpoint(path):
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8010" + path, timeout=8
        ) as response:
            data = response.read(300_001)
            if len(data) > 300_000:
                return {"status": "response_too_large"}
            body = json.loads(data)
            if not isinstance(body, dict):
                return {"status": "unexpected_response"}
            if path.endswith("/debt"):
                return {
                    "status": "observed",
                    "items": {
                        key: body.get("items", {}).get(key)
                        for key in (
                            "declared_services_not_running",
                            "vital_chain_gaps",
                            "backup_protection_gaps",
                            "tables_with_writer_and_no_rows",
                            "entrypoints_without_launcher",
                        )
                    },
                }
            # Do not dump broad API responses that may contain private configuration.
            keys = (
                "status",
                "mode",
                "work_mode",
                "background_thread_alive",
                "last_error",
                "can_run_workers",
                "can_nourish_neurons",
            )
            return {
                "status": "observed",
                "fields": {key: body[key] for key in keys if key in body},
            }
    except urllib.error.HTTPError as exc:
        return {"status": "http_error", "http_status": exc.code}
    except (OSError, ValueError):
        return {"status": "not_observed"}


def audit(r5, seconds=30):
    if not 0 <= seconds <= 120:
        raise ValueError("Audit window must be between 0 and 120 seconds")
    before, errors_before = snapshot(r5.DB)
    print(
        f"Auditor corregido: comparando {seconds} s; no modifica memoria ni reinicia servicios.",
        flush=True,
    )
    time.sleep(seconds)
    after, errors_after = snapshot(r5.DB)
    deltas = {
        key: after[key] - before[key]
        if type(after.get(key)) is int and type(before.get(key)) is int
        else None
        for key in COUNTERS
    }
    result = {
        "audit_version": "schema-aware-1",
        "at": dt.datetime.now(dt.UTC).isoformat(),
        "window_seconds": seconds,
        "metric": "row_count",
        "before": before,
        "after": after,
        "deltas": deltas,
        "schema_notes": {"before": errors_before, "after": errors_after},
        "details": details(r5.DB, before.get("event_cursor")),
        "effective_config": effective_config(r5.WORK),
        "endpoints": {
            path: endpoint(path)
            for path in (
                "/health/live",
                "/api/runtime/workers-always-on/status",
                "/api/system/work-mode",
                "/api/internal-graphs/debt",
            )
        },
        "full_certified": False,
        "interpretation": "Events alone do not prove task completion or applied learning. Pending count alone does not establish eligibility.",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def install(r5):
    """Replace only the notebook audit callback; no backend or database writes."""
    r5.audit_progress = lambda seconds=30: audit(r5, seconds)

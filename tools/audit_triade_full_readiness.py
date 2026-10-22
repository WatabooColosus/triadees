"""Read-only Tríade Ω evidence audit for an offline Colab/Drive SQLite snapshot.

This does not operate the runtime, mutate tables, promote neurons, or infer
consciousness. Zero rows are reported as absent evidence, never filled in.
The JSON contains aggregates rather than message contents or model prompts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

# Tables are a fixed allowlist: no untrusted identifier interpolation.
EVIDENCE_TABLES = (
    "neurons", "neuron_education_sessions", "neuron_activity",
    "triade_weight_events", "governed_research_runs",
    "improvement_proposals", "improvement_canaries",
    "federated_nodes", "trainable_adapters", "worker_runs",
    "worker_events", "autonomous_tasks", "runtime_health_snapshots",
    "metabolic_cycle", "neuron_missions",
)


def _age(timestamp: str | None, now: dt.datetime) -> float | None:
    if not timestamp:
        return None
    try:
        instant = dt.datetime.fromisoformat(timestamp)
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=dt.UTC)
        return max(0.0, round((now - instant).total_seconds(), 2))
    except (TypeError, ValueError):
        return None


def _rows(conn: sqlite3.Connection, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, args).fetchall()]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(database: Path, *, fingerprint: bool = False, now: dt.datetime | None = None) -> dict[str, Any]:
    """Inspect one file in SQLite read-only mode; no changes to its WAL."""
    database = database.resolve()
    if not database.is_file():
        raise FileNotFoundError(f"SQLite snapshot not found: {database}")
    now = now or dt.datetime.now(dt.UTC)
    result: dict[str, Any] = {
        "audit": "triade_full_readiness_v1",
        "generated_at": now.isoformat(),
        "source": {
            "path": str(database),
            "bytes": database.stat().st_size,
            "file_sha256": _sha256(database) if fingerprint else None,
            "read_only": True,
            "scope": "point_in_time_database_not_active_colab_process",
            "sha256_scope": "main_db_file_only_wal_sidecars_not_included",
        },
        "checks": {},
        "counts": {},
        "task_states": {},
        "worker": {},
        "learning": {},
        "gaps": [],
        "full_certification": "not_established",
    }
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=10)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        result["checks"]["sqlite_integrity"] = integrity
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        result["checks"]["table_count"] = len(tables)
        for name in EVIDENCE_TABLES:
            result["counts"][name] = (
                int(conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
                if name in tables
                else None
            )
        if "autonomous_tasks" in tables:
            result["task_states"] = {
                str(row["status"]): row["n"]
                for row in _rows(conn, "SELECT status, COUNT(*) AS n FROM autonomous_tasks GROUP BY status")
            }
        if "worker_runs" in tables:
            runs = _rows(
                conn,
                "SELECT run_ref, status, started_at, finished_at, summary_json "
                "FROM worker_runs ORDER BY id DESC LIMIT 1",
            )
            if runs:
                run = runs[0]
                try:
                    summary = json.loads(run["summary_json"] or "{}")
                except (TypeError, ValueError):
                    summary = {}
                result["worker"] = {
                    "last_run_ref": run["run_ref"],
                    "status": run["status"],
                    "started_at": run["started_at"],
                    "age_seconds": _age(run["started_at"], now),
                    "reported_iterations": summary.get("iterations"),
                }
                if "worker_events" in tables:
                    ev = _rows(
                        conn,
                        "SELECT COUNT(*) n, MAX(created_at) last_at, "
                        "SUM(CASE WHEN event_type='task_completed' THEN 1 ELSE 0 END) completed "
                        "FROM worker_events WHERE run_ref=?",
                        (run["run_ref"],),
                    )[0]
                    result["worker"].update({
                        "events_in_run": int(ev["n"]),
                        "completed_task_events_in_run": int(ev["completed"] or 0),
                        "last_event_at": ev["last_at"],
                        "last_event_age_seconds": _age(ev["last_at"], now),
                        "unfinished_summary_despite_events": (
                            run["status"] == "running"
                            and summary.get("iterations") == 0
                            and int(ev["n"]) > 0
                        ),
                    })
        if "runtime_health_snapshots" in tables:
            health = _rows(
                conn, "SELECT state, created_at, metrics_json "
                "FROM runtime_health_snapshots ORDER BY snapshot_id DESC LIMIT 1"
            )
            if health:
                snap = health[0]
                try:
                    metrics = json.loads(snap["metrics_json"] or "{}")
                except (TypeError, ValueError):
                    metrics = {}
                result["checks"]["health_at_snapshot"] = snap["state"]
                result["checks"]["health_snapshot_age_seconds"] = _age(
                    snap["created_at"], now
                )
                result["checks"]["ollama_ok_at_snapshot"] = bool(
                    (metrics.get("ollama") or {}).get("ollama_ok")
                )
                # Snapshot health isn't live verification.
        if "neuron_education_sessions" in tables:
            states = _rows(
                conn,
                "SELECT result, COUNT(*) AS n FROM neuron_education_sessions GROUP BY result",
            )
            result["learning"]["education_results"] = {
                str(row["result"]): row["n"] for row in states
            }
        if "triade_weight_events" in tables:
            result["learning"]["weight_event_count"] = result["counts"]["triade_weight_events"]

    missing = [name for name, count in result["counts"].items() if count is None]
    absent = [
        name for name in (
            "improvement_proposals", "improvement_canaries",
            "trainable_adapters", "federated_nodes",
        ) if result["counts"][name] == 0
    ]
    if integrity != "ok":
        result["gaps"].append("database_integrity_not_ok")
    if missing:
        result["gaps"].append("missing_evidence_tables: " + ", ".join(missing))
    if absent:
        result["gaps"].append("no_observed_rows: " + ", ".join(absent))
    if result["worker"].get("unfinished_summary_despite_events"):
        result["gaps"].append("worker_summary_not_updated_while_running")
    result["checks"]["historical_task_activity_observed"] = (
        result["task_states"].get("completed", 0) > 0
    )
    result["checks"]["historical_weight_updates_observed"] = (
        (result["counts"].get("triade_weight_events") or 0) > 0
    )
    result["checks"]["autonomous_self_improvement_circuit_certified"] = False
    result["checks"]["end_to_end_colab_upgrade_certified"] = False
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db", type=Path,
        default=Path("/content/Triade/triade/memory/triade.db"),
    )
    parser.add_argument("--sha256", action="store_true", help="Hash the main DB file.")
    parser.add_argument("--output", type=Path, help="Optional JSON report destination.")
    args = parser.parse_args()
    result = audit(args.db, fingerprint=args.sha256)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["checks"]["sqlite_integrity"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

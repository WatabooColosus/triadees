"""Journal operativo de aprendizaje de 24h para Tríade Ω."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from triade.services.event_bus import list_recent_events


def build_learning_journal(
    db_path: str | Path = "triade/memory/triade.db",
    since_hours: int = 24,
    limit: int = 50,
) -> dict[str, Any]:
    """Resume actividad de aprendizaje reciente sin modificar identidad núcleo."""
    db_path = Path(db_path)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(since_hours)))
    cutoff_iso = cutoff.isoformat()

    try:
        cycles = _query_rows(
            db_path,
            "SELECT id, mission_id, neuron_id, cycle_type, input_summary, output_summary, evidence_refs_json, duration_ms, status, created_at "
            "FROM neuron_work_cycles WHERE created_at >= ? ORDER BY id DESC LIMIT ?",
            (cutoff_iso, limit),
        )
        evidence = _query_rows(
            db_path,
            "SELECT id, mission_id, neuron_id, evidence_type, source, content, refs_json, score, created_at "
            "FROM neuron_evidence WHERE created_at >= ? ORDER BY id DESC LIMIT ?",
            (cutoff_iso, limit),
        )
        candidates_recent = _query_rows(
            db_path,
            "SELECT candidate_id, source_type, source_ref, title, domain, risk_level, confidence, utility, status, run_use_count, avg_outcome_score, updated_at, created_at "
            "FROM learning_queue WHERE created_at >= ? OR updated_at >= ? ORDER BY updated_at DESC, id DESC LIMIT ?",
            (cutoff_iso, cutoff_iso, limit),
        )
    except sqlite3.Error:
        cycles = []
        evidence = []
        candidates_recent = []
    try:
        semantic_activity = _query_rows(
            db_path,
            "SELECT id, key, value, status, domain, created_at, updated_at "
            "FROM semantic_memory WHERE created_at >= ? OR updated_at >= ? ORDER BY id DESC LIMIT ?",
            (cutoff_iso, cutoff_iso, limit),
        )
    except sqlite3.Error:
        semantic_activity = []

    recent_events = [
        event for event in list_recent_events(limit=max(limit * 2, 100), db_path=db_path)
        if _is_recent(event.get("created_at"), cutoff)
    ]

    candidates_by_status = _count_candidates_recent(candidates_recent)
    cycles_last_24h = len(cycles)
    evidence_created = len(evidence)
    missions_executed = len({row.get("mission_id") for row in cycles if row.get("mission_id") is not None})
    neurons_nourished = len({
        int(row.get("neuron_id"))
        for row in cycles + evidence
        if row.get("neuron_id") is not None
    })

    latest_learning_candidates = [row for row in candidates_recent if row.get("status") in {"candidate", "evaluated", "verified"}][:limit]
    latest_consolidations = [row for row in candidates_recent if row.get("status") == "consolidated"][:limit]
    latest_rejections = [row for row in candidates_recent if row.get("status") == "rejected"][:limit]

    return {
        "status": "ok",
        "since_hours": since_hours,
        "cycles_last_24h": cycles_last_24h,
        "missions_executed": missions_executed,
        "evidence_created": evidence_created,
        "candidates_created": candidates_by_status.get("candidate", 0),
        "candidates_evaluated": candidates_by_status.get("evaluated", 0),
        "candidates_verified": candidates_by_status.get("verified", 0),
        "candidates_consolidated": candidates_by_status.get("consolidated", 0),
        "candidates_rejected": candidates_by_status.get("rejected", 0),
        "neurons_nourished": neurons_nourished,
        "latest_events": recent_events[:limit],
        "latest_learning_candidates": latest_learning_candidates,
        "latest_consolidations": latest_consolidations,
        "latest_rejections": latest_rejections,
        "semantic_memory_activity": {
            "count": len(semantic_activity),
            "latest": semantic_activity[:limit],
        },
        "truth": "Aprender significa crear, evaluar, verificar o consolidar candidatos con evidencia; no solo responder.",
    }


def _query_rows(db_path: Path, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def _is_recent(value: Any, cutoff: datetime) -> bool:
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts >= cutoff


def _count_candidates_recent(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {
        "candidate": 0,
        "evaluated": 0,
        "verified": 0,
        "validated_in_runs": 0,
        "consolidated": 0,
        "rejected": 0,
    }
    for row in rows:
        status = str(row.get("status") or "candidate")
        counts[status] = counts.get(status, 0) + 1
    return counts

"""Observaciones fisiológicas de edge_context.

Una salida vacía/no JSON del modelo edge no es crash: es señal de calidad.
Se registra como evento operativo y, si se repite, alimenta diagnóstico técnico.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now
from triade.services.event_bus import list_recent_events, publish_event


REPEATED_EDGE_SIGNAL_THRESHOLD = 3
EDGE_SIGNAL_EVENT = "edge_context_signal_observed"


def record_edge_observation(
    parser_name: str,
    observation_type: str,
    signal_quality: str,
    fallback_used: bool,
    raw_preview: str,
    user_text_preview: str,
    node_id: str | None = None,
    model_name: str | None = None,
    run_id: str | None = None,
    *,
    db_path: str | Path = "triade/memory/triade.db",
) -> dict[str, Any]:
    severity = "info" if observation_type == "valid_json" else "warning"
    payload = {
        "parser_name": parser_name,
        "observation_type": observation_type,
        "signal_quality": signal_quality,
        "fallback_used": bool(fallback_used),
        "raw_preview": str(raw_preview or "")[:300],
        "user_text_preview": str(user_text_preview or "")[:300],
        "node_id": node_id,
        "model_name": model_name,
        "run_id": run_id,
        "message": f"edge_context {parser_name}: {observation_type}",
    }
    event = publish_event(
        EDGE_SIGNAL_EVENT,
        "edge_context",
        payload,
        severity=severity,
        db_path=db_path,
        run_ref=run_id,
        task_type="edge_context",
    )
    if observation_type in {"empty_response", "non_json_response", "malformed_json"}:
        maybe_create_edge_learning_candidate(
            parser_name=parser_name,
            observation_type=observation_type,
            event_id=event.get("event_id"),
            db_path=db_path,
        )
    return event


def build_edge_context_health(
    *,
    since_hours: int = 24,
    limit: int = 200,
    db_path: str | Path = "triade/memory/triade.db",
) -> dict[str, Any]:
    observations = _recent_edge_observations(since_hours=since_hours, limit=limit, db_path=db_path)
    total = len(observations)
    fallback_count = sum(1 for obs in observations if obs.get("fallback_used"))
    empty_count = sum(1 for obs in observations if obs.get("observation_type") == "empty_response")
    malformed_count = sum(1 for obs in observations if obs.get("observation_type") == "malformed_json")
    non_json_count = sum(1 for obs in observations if obs.get("observation_type") == "non_json_response")
    degraded_count = empty_count + malformed_count + non_json_count
    last = observations[0] if observations else {}

    if empty_count >= REPEATED_EDGE_SIGNAL_THRESHOLD:
        status = "empty_response_repeated"
        recommendation = "Reforzar prompt JSON del edge_context o cambiar modelo/nodo."
    elif malformed_count + non_json_count >= REPEATED_EDGE_SIGNAL_THRESHOLD:
        status = "malformed_repeated"
        recommendation = "Reforzar prompt JSON del edge_context o cambiar modelo/nodo."
    elif degraded_count:
        status = "degraded"
        recommendation = "Monitorear edge_context; fallback heurístico activo."
    else:
        status = "ok"
        recommendation = "Sin degradación edge_context reciente."

    return {
        "status": status,
        "last_observation_type": last.get("observation_type"),
        "last_signal_quality": last.get("signal_quality"),
        "fallback_rate_24h": round(fallback_count / total, 3) if total else 0.0,
        "empty_count_24h": empty_count,
        "malformed_count_24h": malformed_count,
        "non_json_count_24h": non_json_count,
        "total_observations_24h": total,
        "recommended_action": recommendation,
        "recent_observations": observations[:10],
        "updated_at": utc_now(),
    }


def maybe_create_edge_learning_candidate(
    *,
    parser_name: str,
    observation_type: str,
    event_id: int | None,
    db_path: str | Path = "triade/memory/triade.db",
) -> dict[str, Any]:
    repeated = _count_recent_observation(observation_type, db_path=db_path)
    if repeated < REPEATED_EDGE_SIGNAL_THRESHOLD:
        return {"status": "skipped", "reason": "not_repeated", "count_24h": repeated}
    try:
        from triade.learning.pipeline import LearningPipeline

        pipeline = LearningPipeline(db_path=db_path)
        title = f"edge_context {parser_name} {observation_type}"
        existing = next(
            (
                c for c in pipeline.list_candidates(limit=100)
                if c.get("domain") == "system_edge_context"
                and c.get("title") == title
                and c.get("status") in {"candidate", "evaluated", "verified", "validated_in_runs"}
            ),
            None,
        )
        if existing:
            return {
                "status": "candidate_exists",
                "candidate_id": existing.get("candidate_id"),
                "count_24h": repeated,
            }
        candidate = pipeline.ingest(
            content=(
                f"edge_context {parser_name} returned {observation_type}; "
                "fallback heurístico permitió continuar, pero se requiere diagnóstico del prompt/modelo JSON."
            ),
            source_type="tool",
            source_ref=f"worker_events:{event_id}" if event_id else "worker_events:edge_context",
            title=title,
            domain="system_edge_context",
            risk_level="low",
        )
        publish_event(
            "edge_context_learning_candidate_created",
            "edge_context",
            {
                "candidate_id": candidate.get("candidate_id"),
                "domain": "system_edge_context",
                "claim": f"edge_context {parser_name} returned {observation_type}",
                "evidence_ref": f"worker_events:{event_id}" if event_id else None,
                "confidence": "low",
                "repetition_count_24h": repeated,
            },
            severity="warning",
            db_path=db_path,
            task_type="edge_context",
        )
        return {"status": "candidate_created", "candidate_id": candidate.get("candidate_id"), "count_24h": repeated}
    except Exception as exc:
        from triade.core.error_bus import record_internal_error

        record_internal_error(
            "edge_context.learning_candidate",
            exc,
            payload={"parser_name": parser_name, "observation_type": observation_type, "event_id": event_id},
            db_path=db_path,
            severity="warning",
        )
        return {"status": "error", "error": str(exc)[:200], "count_24h": repeated}


def _count_recent_observation(
    observation_type: str,
    *,
    db_path: str | Path,
    since_hours: int = 24,
) -> int:
    observations = _recent_edge_observations(since_hours=since_hours, limit=500, db_path=db_path)
    return sum(1 for obs in observations if obs.get("observation_type") == observation_type)


def _recent_edge_observations(
    *,
    since_hours: int,
    limit: int,
    db_path: str | Path,
) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    rows = list_recent_events(limit=limit, db_path=db_path)
    observations: list[dict[str, Any]] = []
    for row in rows:
        if row.get("event_type") != EDGE_SIGNAL_EVENT:
            continue
        created_at = _parse_datetime(row.get("created_at"))
        if created_at and created_at < cutoff:
            continue
        event_payload = row.get("payload") or {}
        payload = event_payload.get("payload") if isinstance(event_payload.get("payload"), dict) else event_payload
        observations.append({
            "event_id": row.get("id"),
            "created_at": row.get("created_at"),
            "parser_name": payload.get("parser_name"),
            "observation_type": payload.get("observation_type"),
            "signal_quality": payload.get("signal_quality"),
            "fallback_used": bool(payload.get("fallback_used")),
            "node_id": payload.get("node_id"),
            "model_name": payload.get("model_name"),
        })
    return observations


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed

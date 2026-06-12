"""Selector de misiones neuronales por relevancia.

Tríade Ω — Mission Selector

Lee misiones desde NeuronMissionStore y las filtra por relevancia
basándose en dominio, keywords, estado y score reciente.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .neuron_missions import NeuronMission, NeuronMissionStore


def select_relevant_missions(
    user_input: str = "",
    domain: str | None = None,
    memory_context: dict[str, Any] | None = None,
    db_path: str | Path = "triade/memory/triade.db",
    limit: int = 5,
) -> dict[str, Any]:
    """Selecciona misiones relevantes desde la base de datos.

    Lee todas las misiones activas y las puntúa por:
    - domain coincide
    - palabras clave de mission/title en user_input
    - domain en memory_context
    - latest_score si existe
    - updated_at reciente

    Returns:
        Dict con status, count, selected, rejected, policy.
    """
    store = NeuronMissionStore(db_path=db_path)
    all_missions = store.list_missions(limit=200)

    active_statuses = {"candidate", "experimental", "stable"}
    user_lower = user_input.lower()
    user_words = {w for w in user_lower.split() if len(w) > 3}
    memory_domains: set[str] = set()

    if memory_context:
        project = memory_context.get("project_context") or {}
        if isinstance(project, dict):
            d = project.get("domain", "")
            if d:
                memory_domains.add(d.lower())
            for extra_key in ("domains", "topics", "keywords"):
                extra = project.get(extra_key)
                if isinstance(extra, list):
                    memory_domains.update(str(item).lower() for item in extra if item)
        active_neuron = memory_context.get("active_neuron", "")
        if isinstance(active_neuron, str) and active_neuron:
            memory_domains.add(active_neuron.lower())
        direct_domain = memory_context.get("domain")
        if isinstance(direct_domain, str) and direct_domain:
            memory_domains.add(direct_domain.lower())

    scored: list[tuple[float, NeuronMission, str]] = []
    rejected: list[dict[str, Any]] = []

    for m in all_missions:
        if m.status not in active_statuses:
            rejected.append({
                "id": m.id,
                "title": m.title,
                "domain": m.domain,
                "status": m.status,
                "reason": f"status '{m.status}' not in active set",
            })
            continue

        score = 0.0
        reasons: list[str] = []
        primary_signal = False

        if domain and m.domain == domain:
            score += 2.0
            reasons.append("domain_match")
            primary_signal = True

        if user_words:
            mission_lower = m.mission.lower()
            title_lower = m.title.lower()
            matching_words = [w for w in user_words if w in mission_lower or w in title_lower]
            if matching_words:
                score += 1.0 + (0.2 * len(matching_words))
                reasons.append(f"keyword_match:{','.join(matching_words[:3])}")
                primary_signal = True

        if memory_domains and m.domain.lower() in memory_domains:
            score += 1.0
            reasons.append("memory_context_domain")
            primary_signal = True

        mission_id = int(m.id or 0)
        if mission_id > 0:
            try:
                latest = store.latest_score(mission_id)
                if latest and latest.value > 0:
                    score += latest.value
                    reasons.append(f"latest_score:{latest.value:.2f}")
                    primary_signal = True
            except Exception:
                pass

        if m.updated_at:
            recency_bonus = _updated_at_bonus(m.updated_at)
            if recency_bonus > 0:
                score += recency_bonus
                reasons.append(f"recency_bonus:{recency_bonus:.2f}")
            reasons.append(f"updated:{m.updated_at[:10]}")

        if score > 0 and primary_signal:
            scored.append((score, m, "; ".join(reasons)))

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [
        {
            "id": m.id,
            "title": m.title,
            "mission": m.mission,
            "domain": m.domain,
            "status": m.status,
            "schedule_hint": m.schedule_hint,
            "relevance_score": round(s, 3),
            "reason": r,
        }
        for s, m, r in scored[:limit]
    ]

    return {
        "status": "ok",
        "count": len(selected),
        "selected": selected,
        "rejected": rejected,
        "policy": {
            "active_status_only": True,
            "no_identity_core_modification": True,
            "selector_is_read_only": True,
        },
    }


def _updated_at_bonus(updated_at: str) -> float:
    """Da más puntuación a misiones recientemente actualizadas."""
    try:
        ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0)
    if age_days <= 1:
        return 0.6
    if age_days <= 7:
        return 0.4
    if age_days <= 30:
        return 0.2
    return 0.05

"""Planificación determinista de revisión basada en desempeño."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def next_review_for(result: str, *, changing_knowledge: bool = False) -> str:
    days = {
        "incorrect": 0,
        "insufficient_material": 0,
        "uncertain": 1,
        "correct_new": 3,
        "consolidated": 14,
    }.get(result, 1)
    if changing_knowledge:
        days = min(days or 1, 7)
    delay = timedelta(minutes=30) if days == 0 else timedelta(days=days)
    return (datetime.now(UTC) + delay).isoformat()

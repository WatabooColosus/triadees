"""Cálculo de estado Qualia agregado."""

from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any

from .contracts import QualiaState


def _avg(rows: list[dict[str, Any]], key: str) -> float:
    vals = [float(row.get(key) or 0.0) for row in rows]
    return round(mean(vals), 3) if vals else 0.0


def compute_qualia_state(run_id: str, signals: list[dict[str, Any]], experiences: list[dict[str, Any]]) -> QualiaState:
    count = len(signals)
    dominant = "none"
    if signals:
        dominant = Counter(str(row.get("signal_type") or "observation") for row in signals).most_common(1)[0][0]
    risk = _avg(signals, "risk")
    urgency = _avg(signals, "urgency")
    confidence = _avg(signals, "confidence")
    curiosity = _avg(signals, "curiosity")
    usefulness = round(mean([float(row.get("usefulness") or 0.0) for row in experiences]), 3) if experiences else 0.0
    novelty = min(1.0, round(count / 10.0, 3))
    saturation = min(1.0, round(max(0, count - 5) / 10.0, 3))
    coherence = round(max(0.0, min(1.0, (confidence + usefulness + (1.0 - risk)) / 3.0)), 3) if count else 0.0
    if risk >= 0.75:
        action = "review_safety"
    elif any(str(exp.get("proposed_learning") or "").strip() for exp in experiences):
        action = "review_learning_candidates"
    elif curiosity >= 0.55:
        action = "observe_and_validate"
    else:
        action = "observe"
    return QualiaState(
        run_id=run_id,
        curiosity=curiosity,
        confidence=confidence,
        risk=risk,
        urgency=urgency,
        coherence=coherence,
        novelty=novelty,
        usefulness=usefulness,
        saturation=saturation,
        dominant_signal=dominant,
        recommended_action=action,
    )

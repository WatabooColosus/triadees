"""Estimadores ligeros de calidad para eventos de modelo."""

from __future__ import annotations

from typing import Any


def score_hypothalamus(signals: Any, model_result: dict[str, Any]) -> float:
    score = 0.55
    if model_result.get("ok"):
        score += 0.20
    if signals.intent in {"conversation", "build_or_update", "analyze", "memory"}:
        score += 0.10
    if signals.risk in {"low", "medium", "high", "critical"}:
        score += 0.05
    if isinstance(signals.pv7, dict) and len(signals.pv7) >= 7:
        score += 0.05
    if signals.notes:
        score += 0.05
    return round(min(score, 1.0), 3)


def score_central(response: str, model_ok: bool) -> float:
    score = 0.50 + (0.20 if model_ok else 0.0)
    if response and len(response.strip()) > 20:
        score += 0.10
    if any(marker in response.lower() for marker in ["verific", "traz", "memoria", "cristal", "riesgo"]):
        score += 0.10
    return round(min(score, 1.0), 3)

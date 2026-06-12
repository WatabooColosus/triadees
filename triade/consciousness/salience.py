from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SalienceVector:
    relevance: float = 0.0
    emotional_salience: float = 0.0
    goal_salience: float = 0.0
    novelty_salience: float = 0.0
    urgency_salience: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "relevance": round(self.relevance, 4),
            "emotional_salience": round(self.emotional_salience, 4),
            "goal_salience": round(self.goal_salience, 4),
            "novelty_salience": round(self.novelty_salience, 4),
            "urgency_salience": round(self.urgency_salience, 4),
        }


@dataclass(slots=True)
class SalienceEngine:
    db_path: str | Path = "triade/memory/triade.db"
    _mood_cache: dict[str, float] = field(default_factory=dict, init=False)

    WEIGHTS = {
        "emotional": 0.30,
        "goal": 0.25,
        "novelty": 0.20,
        "urgency": 0.25,
    }

    def score(self, user_input: str, intent: str, urgency: str, risk: str, tone: str) -> SalienceVector:
        emotional = self._emotional_salience(user_input, tone)
        goal = self._goal_salience(user_input)
        novelty = self._novelty_salience(user_input)
        urgency_sal = self._urgency_salience(urgency, risk)

        total = (
            self.WEIGHTS["emotional"] * emotional
            + self.WEIGHTS["goal"] * goal
            + self.WEIGHTS["novelty"] * novelty
            + self.WEIGHTS["urgency"] * urgency_sal
        )
        total = max(0.0, min(1.0, total))

        return SalienceVector(
            relevance=total,
            emotional_salience=emotional,
            goal_salience=goal,
            novelty_salience=novelty,
            urgency_salience=urgency_sal,
        )

    def _emotional_salience(self, user_input: str, tone: str) -> float:
        tone_boost = {"encouraging": 0.3, "cautious": 0.4, "constructive": 0.2}
        base = tone_boost.get(tone, 0.2)
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT mood_valence, mood_arousal FROM hypothalamus_state ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row:
                    valence, arousal = float(row[0]), float(row[1])
                    congruence = 1.0 - abs(valence - 0.5) * 2
                    return max(0.0, min(1.0, base + congruence * 0.3 + arousal * 0.2))
        except Exception as exc:
            from triade.core.error_bus import record_internal_error
            record_internal_error(
                "salience.emotional",
                exc,
                payload={"module": __name__, "function": "_emotional_salience", "operation": "load_hypothalamus_state"},
                db_path=self.db_path,
            )
        return base

    def _goal_salience(self, user_input: str) -> float:
        try:
            with sqlite3.connect(self.db_path) as conn:
                active = conn.execute(
                    "SELECT title, description FROM goals WHERE status = 'active' LIMIT 5"
                ).fetchall()
                if not active:
                    return 0.1
                text_lower = user_input.lower()
                matches = 0
                for title, desc in active:
                    if title and title.lower() in text_lower:
                        matches += 1
                    if desc and any(w in text_lower for w in desc.lower().split()):
                        matches += 0.5
                return max(0.1, min(1.0, matches / len(active)))
        except Exception as exc:
            from triade.core.error_bus import record_internal_error
            record_internal_error(
                "salience.goal",
                exc,
                payload={"module": __name__, "function": "_goal_salience", "operation": "load_active_goals"},
                db_path=self.db_path,
            )
            return 0.1

    def _novelty_salience(self, user_input: str) -> float:
        try:
            with sqlite3.connect(self.db_path) as conn:
                recent = conn.execute(
                    "SELECT user_input FROM runs ORDER BY id DESC LIMIT 10"
                ).fetchall()
                if not recent:
                    return 0.8
                words = set(user_input.lower().split())
                overlap = 0
                for (text,) in recent:
                    if text:
                        shared = words & set(text.lower().split())
                        overlap += len(shared)
                avg_overlap = overlap / len(recent) if recent else 0
                max_possible = len(words)
                if max_possible == 0:
                    return 0.5
                novelty = 1.0 - (avg_overlap / max_possible)
                return max(0.0, min(1.0, novelty))
        except Exception as exc:
            from triade.core.error_bus import record_internal_error
            record_internal_error(
                "salience.novelty",
                exc,
                payload={"module": __name__, "function": "_novelty_salience", "operation": "load_recent_runs"},
                db_path=self.db_path,
            )
            return 0.5

    @staticmethod
    def _urgency_salience(urgency: str, risk: str) -> float:
        urgency_map = {"low": 0.1, "medium": 0.4, "high": 0.8}
        risk_map = {"low": 0.1, "medium": 0.5, "high": 0.8, "critical": 1.0}
        u = urgency_map.get(urgency, 0.2)
        r = risk_map.get(risk, 0.2)
        return max(0.0, min(1.0, u * 0.6 + r * 0.4))

    def doctor(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "weights": self.WEIGHTS,
        }

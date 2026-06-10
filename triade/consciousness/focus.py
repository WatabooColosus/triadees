from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class FocusModulator:
    db_path: str | Path = "triade/memory/triade.db"

    BASE_THRESHOLD: float = 0.20
    MIN_THRESHOLD: float = 0.05
    MAX_THRESHOLD: float = 0.60

    def threshold(self) -> float:
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT mood_valence, mood_arousal, fatigue, primary_emotion "
                    "FROM hypothalamus_state ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row is None:
                    return self.BASE_THRESHOLD
                valence, arousal, fatigue, emotion = (
                    float(row[0]), float(row[1]), float(row[2]), str(row[3])
                )

                modulation = 0.0
                modulation += (0.5 - valence) * 0.3
                modulation += fatigue * 0.3
                modulation += (0.5 - arousal) * 0.2

                emotion_shifts = {
                    "anxious": 0.15,
                    "fatigued": 0.20,
                    "withdrawn": 0.15,
                    "calm": -0.05,
                    "positive": -0.10,
                    "engaged": -0.10,
                    "excited": -0.15,
                }
                modulation += emotion_shifts.get(emotion, 0.0)

                threshold = self.BASE_THRESHOLD + modulation
                return max(self.MIN_THRESHOLD, min(self.MAX_THRESHOLD, threshold))
        except Exception:
            return self.BASE_THRESHOLD

    def should_filter(self, relevance: float) -> bool:
        return relevance < self.threshold()

    def doctor(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "current_threshold": self.threshold(),
            "base_threshold": self.BASE_THRESHOLD,
            "min_threshold": self.MIN_THRESHOLD,
            "max_threshold": self.MAX_THRESHOLD,
        }

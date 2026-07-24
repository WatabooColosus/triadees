"""Verificación independiente, recuperación espaciada, contradicciones,
evaluación por desempeño, olvido y degradación controlados.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from triade.core.contracts import utc_now

EvaluationMode = Literal["spaced_retrieval", "contradiction_check", "performance", "forgetting"]


@dataclass(frozen=True, slots=True)
class SpacedRetrievalItem:
    item_id: str
    content_hash: str
    last_recalled_at: str | None
    recall_count: int
    ease_factor: float
    next_review_at: str
    interval_days: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContradictionReport:
    report_id: str
    knowledge_a: str
    knowledge_b: str
    contradiction_type: str
    severity: str
    resolution: str
    detected_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ForgettingRecord:
    item_id: str
    original_strength: float
    current_strength: float
    reason: str
    forgotten_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LearningEvaluator:
    """Evaluador independiente de conocimiento con múltiples modalidades."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS spaced_retrieval (
                    item_id TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    last_recalled_at TEXT,
                    recall_count INTEGER NOT NULL DEFAULT 0,
                    ease_factor REAL NOT NULL DEFAULT 2.5,
                    next_review_at TEXT NOT NULL,
                    interval_days REAL NOT NULL DEFAULT 1.0
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS contradiction_reports (
                    report_id TEXT PRIMARY KEY,
                    knowledge_a TEXT NOT NULL,
                    knowledge_b TEXT NOT NULL,
                    contradiction_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    resolution TEXT NOT NULL,
                    detected_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS forgetting_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id TEXT NOT NULL,
                    original_strength REAL NOT NULL,
                    current_strength REAL NOT NULL,
                    reason TEXT NOT NULL,
                    forgotten_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS performance_evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    knowledge_id TEXT NOT NULL,
                    score REAL NOT NULL,
                    evaluation_type TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    evaluated_at TEXT NOT NULL
                )"""
            )

    def spaced_retrieval_register(self, item_id: str, content_hash: str) -> SpacedRetrievalItem:
        now = utc_now()
        item = SpacedRetrievalItem(
            item_id=item_id, content_hash=content_hash,
            last_recalled_at=None, recall_count=0,
            ease_factor=2.5, next_review_at=now, interval_days=1.0,
        )
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO spaced_retrieval
                (item_id, content_hash, next_review_at, interval_days)
                VALUES (?, ?, ?, ?)""",
                (item_id, content_hash, now, 1.0),
            )
        return item

    def spaced_retrieval_review(self, item_id: str, quality: float) -> SpacedRetrievalItem:
        if not 0.0 <= quality <= 1.0:
            raise ValueError("quality debe estar entre 0.0 y 1.0")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM spaced_retrieval WHERE item_id = ?", (item_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Item no registrado: {item_id}")
            ease = float(row["ease_factor"])
            interval = float(row["interval_days"])
            count = int(row["recall_count"])
            if quality >= 0.6:
                new_ease = max(1.3, ease + 0.1 - (1.0 - quality) * 0.8)
                new_interval = interval * new_ease
                new_count = count + 1
            else:
                new_ease = max(1.3, ease - 0.2)
                new_interval = 1.0
                new_count = count
            from datetime import datetime, timedelta
            next_review = (datetime.utcnow() + timedelta(days=new_interval)).isoformat()
            conn.execute(
                """UPDATE spaced_retrieval SET
                last_recalled_at=?, recall_count=?, ease_factor=?,
                next_review_at=?, interval_days=?
                WHERE item_id=?""",
                (utc_now(), new_count, round(new_ease, 3),
                 next_review, round(new_interval, 2), item_id),
            )
        return SpacedRetrievalItem(
            item_id=item_id, content_hash=row["content_hash"],
            last_recalled_at=utc_now(), recall_count=new_count,
            ease_factor=round(new_ease, 3), next_review_at=next_review,
            interval_days=round(new_interval, 2),
        )

    def detect_contradiction(
        self, knowledge_a: str, knowledge_b: str,
        contradiction_type: str = "semantic",
        severity: str = "medium",
    ) -> ContradictionReport:
        report_id = f"contradiction-{int(__import__('time').time()*1000)}"
        report = ContradictionReport(
            report_id=report_id, knowledge_a=knowledge_a,
            knowledge_b=knowledge_b, contradiction_type=contradiction_type,
            severity=severity, resolution="pending", detected_at=utc_now(),
        )
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO contradiction_reports
                (report_id, knowledge_a, knowledge_b, contradiction_type, severity, resolution, detected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (report_id, knowledge_a, knowledge_b, contradiction_type,
                 severity, "pending", utc_now()),
            )
        return report

    def evaluate_performance(
        self, knowledge_id: str, score: float,
        evaluation_type: str = "retention",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO performance_evaluations(knowledge_id, score, evaluation_type, details_json, evaluated_at) VALUES (?, ?, ?, ?, ?)",
                (knowledge_id, score, evaluation_type,
                 json.dumps(details or {}, ensure_ascii=False), utc_now()),
            )
        return {
            "knowledge_id": knowledge_id,
            "score": score,
            "type": evaluation_type,
            "recorded": True,
        }

    def apply_forgetting(
        self, item_id: str, reason: str = "decay",
        threshold: float = 0.1,
    ) -> ForgettingRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM performance_evaluations WHERE knowledge_id = ? ORDER BY evaluated_at DESC LIMIT 1",
                (item_id,),
            ).fetchone()
            if row is None:
                return None
            current_score = float(row["score"])
            if current_score > threshold:
                return None
            record = ForgettingRecord(
                item_id=item_id, original_strength=1.0,
                current_strength=current_score, reason=reason,
                forgotten_at=utc_now(),
            )
            conn.execute(
                "INSERT INTO forgetting_log(item_id, original_strength, current_strength, reason, forgotten_at) VALUES (?, ?, ?, ?, ?)",
                (item_id, 1.0, current_score, reason, utc_now()),
            )
        return record

    def doctor(self) -> dict[str, Any]:
        with self._connect() as conn:
            sr = conn.execute("SELECT COUNT(*) as c FROM spaced_retrieval").fetchone()["c"]
            contradictions = conn.execute(
                "SELECT COUNT(*) as c FROM contradiction_reports WHERE resolution='pending'"
            ).fetchone()["c"]
            forgotten = conn.execute("SELECT COUNT(*) as c FROM forgetting_log").fetchone()["c"]
            evaluations = conn.execute("SELECT COUNT(*) as c FROM performance_evaluations").fetchone()["c"]
        return {
            "spaced_retrieval_items": sr,
            "pending_contradictions": contradictions,
            "forgotten_items": forgotten,
            "total_evaluations": evaluations,
        }

"""Estados completos del conocimiento y verificación independiente.

Máquina de estados formal para el conocimiento:
  unknown → candidate → experimental → validated → stable → deprecated
  Cualquier estado puede → quarantined (con rollback)
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from triade.core.contracts import utc_now

KnowledgeState = Literal[
    "unknown", "candidate", "experimental", "validated",
    "stable", "deprecated", "quarantined", "rejected",
]

VALID_KNOWLEDGE_TRANSITIONS: dict[KnowledgeState, set[KnowledgeState]] = {
    "unknown": {"candidate", "rejected"},
    "candidate": {"experimental", "rejected", "quarantined"},
    "experimental": {"validated", "rejected", "quarantined"},
    "validated": {"stable", "rejected", "quarantined"},
    "stable": {"deprecated", "quarantined"},
    "deprecated": set(),
    "quarantined": {"candidate", "rejected"},
    "rejected": set(),
}


@dataclass(frozen=True, slots=True)
class KnowledgeTransition:
    knowledge_id: str
    from_state: KnowledgeState
    to_state: KnowledgeState
    reason: str
    evidence: dict[str, Any]
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnowledgeStateMachine:
    """Máquina de estados para conocimiento con verificación independiente."""

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
                """CREATE TABLE IF NOT EXISTS knowledge_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    knowledge_id TEXT NOT NULL,
                    from_state TEXT NOT NULL,
                    to_state TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    recorded_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_know_trans ON knowledge_transitions(knowledge_id, id)"
            )

    def get_state(self, knowledge_id: str) -> KnowledgeState:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT to_state FROM knowledge_transitions WHERE knowledge_id = ? ORDER BY id DESC LIMIT 1",
                (knowledge_id,),
            ).fetchone()
        return str(row["to_state"]) if row else "unknown"

    def transition(
        self,
        knowledge_id: str,
        to_state: KnowledgeState,
        *,
        reason: str = "",
        evidence: dict[str, Any] | None = None,
    ) -> KnowledgeTransition:
        current = self.get_state(knowledge_id)
        allowed = VALID_KNOWLEDGE_TRANSITIONS.get(current, set())
        if to_state not in allowed:
            raise ValueError(
                f"Transición inválida: {current} → {to_state}. "
                f"Permitidas: {sorted(allowed) or 'ninguna (estado terminal)'}"
            )
        now = utc_now()
        record = KnowledgeTransition(
            knowledge_id=knowledge_id,
            from_state=current,
            to_state=to_state,
            reason=reason,
            evidence=evidence or {},
            timestamp=now,
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO knowledge_transitions(knowledge_id, from_state, to_state, reason, evidence_json, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
                (knowledge_id, current, to_state, reason,
                 json.dumps(record.evidence, ensure_ascii=False), now),
            )
        return record

    def history(self, knowledge_id: str) -> list[KnowledgeTransition]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_transitions WHERE knowledge_id = ? ORDER BY id ASC",
                (knowledge_id,),
            ).fetchall()
        return [
            KnowledgeTransition(
                knowledge_id=r["knowledge_id"],
                from_state=r["from_state"],
                to_state=r["to_state"],
                reason=r["reason"],
                evidence=json.loads(r["evidence_json"] or "{}"),
                timestamp=r["recorded_at"],
            )
            for r in rows
        ]

    def list_by_state(self, state: KnowledgeState) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT knowledge_id FROM knowledge_transitions
                WHERE id IN (SELECT MAX(id) FROM knowledge_transitions GROUP BY knowledge_id)
                AND to_state = ?""",
                (state,),
            ).fetchall()
        return [r["knowledge_id"] for r in rows]

    def doctor(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(DISTINCT knowledge_id) as c FROM knowledge_transitions"
            ).fetchone()["c"]
            by_state = conn.execute(
                """SELECT to_state, COUNT(DISTINCT knowledge_id) as c FROM knowledge_transitions
                WHERE id IN (SELECT MAX(id) FROM knowledge_transitions GROUP BY knowledge_id)
                GROUP BY to_state"""
            ).fetchall()
        return {
            "total_knowledge_items": total,
            "by_state": {r["to_state"]: r["c"] for r in by_state},
            "valid_transitions": {k: sorted(v) for k, v in VALID_KNOWLEDGE_TRANSITIONS.items()},
        }

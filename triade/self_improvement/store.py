"""Persistencia y límites del ciclo de auto-mejora."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Callable, Any

from .contracts import ImprovementProposal, ImprovementSignal


class ImprovementStore:
    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        *,
        max_open_proposals: int = 3,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_open_proposals < 1:
            raise ValueError("max_open_proposals debe ser al menos 1")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_open_proposals = max_open_proposals
        self.clock = clock
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS improvement_signals (
                    signal_id TEXT PRIMARY KEY,
                    capability_id TEXT NOT NULL,
                    metric_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_improvement_signal_lookup
                    ON improvement_signals(capability_id, metric_id, status, created_at);

                CREATE TABLE IF NOT EXISTS improvement_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    signal_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(signal_id) REFERENCES improvement_signals(signal_id)
                );
                CREATE INDEX IF NOT EXISTS idx_improvement_proposal_status
                    ON improvement_proposals(status, created_at);

                CREATE TABLE IF NOT EXISTS improvement_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def register_signal(self, signal: ImprovementSignal) -> dict[str, Any]:
        signal.validate()
        now = self.clock()
        payload = signal.to_dict()
        with self._connect() as conn:
            duplicate = conn.execute(
                """SELECT signal_id FROM improvement_signals
                WHERE capability_id = ? AND metric_id = ? AND status = 'open'
                LIMIT 1""",
                (signal.capability_id, signal.metric_id),
            ).fetchone()
            if duplicate:
                raise ValueError(
                    f"ya existe una señal abierta para {signal.capability_id}:{signal.metric_id}"
                )
            try:
                conn.execute(
                    """INSERT INTO improvement_signals
                    (signal_id, capability_id, metric_id, status, priority, payload_json, created_at)
                    VALUES (?, ?, ?, 'open', ?, ?, ?)""",
                    (
                        signal.signal_id,
                        signal.capability_id,
                        signal.metric_id,
                        payload["priority"],
                        json.dumps(payload, sort_keys=True),
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("signal_id ya registrado") from exc
            self._history(conn, "signal", signal.signal_id, "registered", payload, now)
        return {**payload, "status": "open"}

    def create_proposal(self, proposal: ImprovementProposal) -> dict[str, Any]:
        proposal.validate()
        now = self.clock()
        payload = {
            "proposal_id": proposal.proposal_id,
            "signal_id": proposal.signal_id,
            "hypothesis": proposal.hypothesis,
            "requested_capability": proposal.requested_capability,
            "requires_human_approval": proposal.requires_human_approval,
            "max_candidates": proposal.max_candidates,
            "cooldown_seconds": proposal.cooldown_seconds,
        }
        with self._connect() as conn:
            signal = conn.execute(
                "SELECT payload_json, status FROM improvement_signals WHERE signal_id = ?",
                (proposal.signal_id,),
            ).fetchone()
            if signal is None:
                raise KeyError(f"señal no registrada: {proposal.signal_id}")
            if signal["status"] != "open":
                raise ValueError("la señal no está abierta")
            signal_payload = json.loads(signal["payload_json"])
            if signal_payload["capability_id"] != proposal.requested_capability:
                raise ValueError("la propuesta no corresponde a la capacidad de la señal")

            open_count = conn.execute(
                "SELECT COUNT(*) AS total FROM improvement_proposals WHERE status = 'open'"
            ).fetchone()["total"]
            if open_count >= self.max_open_proposals:
                raise ValueError("se alcanzó el límite global de propuestas abiertas")

            latest = conn.execute(
                """SELECT created_at FROM improvement_proposals
                WHERE signal_id = ? ORDER BY created_at DESC LIMIT 1""",
                (proposal.signal_id,),
            ).fetchone()
            if latest and now - float(latest["created_at"]) < proposal.cooldown_seconds:
                raise ValueError("la señal está dentro del periodo de cooldown")

            if signal_payload["risk_level"] in {"high", "critical"} and not proposal.requires_human_approval:
                raise ValueError("el riesgo alto o crítico requiere aprobación humana")

            try:
                conn.execute(
                    """INSERT INTO improvement_proposals
                    (proposal_id, signal_id, status, payload_json, created_at)
                    VALUES (?, ?, 'open', ?, ?)""",
                    (proposal.proposal_id, proposal.signal_id, json.dumps(payload, sort_keys=True), now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("proposal_id ya registrado") from exc
            self._history(conn, "proposal", proposal.proposal_id, "created", payload, now)
        return {**payload, "status": "open"}

    def close_proposal(self, proposal_id: str, *, outcome: str) -> dict[str, Any]:
        if outcome not in {"completed", "rejected", "cancelled"}:
            raise ValueError("outcome inválido")
        now = self.clock()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json, status FROM improvement_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"propuesta no registrada: {proposal_id}")
            if row["status"] != "open":
                raise ValueError("la propuesta ya está cerrada")
            payload = json.loads(row["payload_json"])
            conn.execute(
                "UPDATE improvement_proposals SET status = ? WHERE proposal_id = ?",
                (outcome, proposal_id),
            )
            self._history(conn, "proposal", proposal_id, outcome, payload, now)
        return {**payload, "status": outcome}

    def history(self, entity_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT entity_type, action, payload_json, created_at
                FROM improvement_history WHERE entity_id = ? ORDER BY id""",
                (entity_id,),
            ).fetchall()
        return [
            {
                "entity_type": row["entity_type"],
                "action": row["action"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    @staticmethod
    def _history(
        conn: sqlite3.Connection,
        entity_type: str,
        entity_id: str,
        action: str,
        payload: dict[str, Any],
        created_at: float,
    ) -> None:
        conn.execute(
            """INSERT INTO improvement_history
            (entity_type, entity_id, action, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)""",
            (entity_type, entity_id, action, json.dumps(payload, sort_keys=True), created_at),
        )

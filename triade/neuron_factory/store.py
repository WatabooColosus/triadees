"""Persistencia e historial de especificaciones de neuronas."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from .specification import NeuronSpecification, ResourceBudget, validate_transition


class NeuronSpecificationStore:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS neuron_specifications (
                    neuron_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (neuron_id, version)
                );
                CREATE TABLE IF NOT EXISTS neuron_specification_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    neuron_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_neuron_spec_history
                    ON neuron_specification_history(neuron_id, version, id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def register(self, specification: NeuronSpecification) -> dict[str, Any]:
        specification.validate()
        payload_json = json.dumps(specification.to_dict(), sort_keys=True)
        payload = json.loads(payload_json)
        with self._connect() as conn:
            try:
                conn.execute(
                    """INSERT INTO neuron_specifications
                    (neuron_id, version, state, payload_json)
                    VALUES (?, ?, ?, ?)""",
                    (specification.neuron_id, specification.version, specification.state, payload_json),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("especificación ya registrada") from exc
            self._append_history(conn, specification.neuron_id, specification.version, "registered", payload)
        return payload

    def get(self, neuron_id: str, version: str | None = None) -> dict[str, Any] | None:
        sql = "SELECT payload_json FROM neuron_specifications WHERE neuron_id = ?"
        params: list[Any] = [neuron_id]
        if version:
            sql += " AND version = ?"
            params.append(version)
        sql += " ORDER BY created_at DESC, version DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def transition(self, neuron_id: str, version: str, target: str) -> dict[str, Any]:
        payload = self.get(neuron_id, version)
        if payload is None:
            raise KeyError(f"especificación no registrada: {neuron_id}@{version}")
        current = str(payload["state"])
        validate_transition(current, target)
        payload["state"] = target
        with self._connect() as conn:
            conn.execute(
                """UPDATE neuron_specifications
                SET state = ?, payload_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE neuron_id = ? AND version = ?""",
                (target, json.dumps(payload, sort_keys=True), neuron_id, version),
            )
            self._append_history(
                conn,
                neuron_id,
                version,
                "state_changed",
                {"from": current, "to": target, "snapshot": payload},
            )
        return payload

    def history(self, neuron_id: str, version: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT action, payload_json, created_at FROM neuron_specification_history WHERE neuron_id = ?"
        params: list[Any] = [neuron_id]
        if version:
            sql += " AND version = ?"
            params.append(version)
        sql += " ORDER BY id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "action": row["action"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def export(self, neuron_id: str, version: str | None = None) -> dict[str, Any]:
        payload = self.get(neuron_id, version)
        if payload is None:
            raise KeyError(f"especificación no registrada: {neuron_id}")
        resolved_version = str(payload["version"])
        document = {
            "schema_version": "1.0.0",
            "specification": payload,
            "history": self.history(neuron_id, resolved_version),
        }
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
        document["sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return document

    @staticmethod
    def from_payload(payload: dict[str, Any]) -> NeuronSpecification:
        data = dict(payload)
        budget = data.get("resource_budget")
        data["resource_budget"] = ResourceBudget(**budget) if budget else None
        for field in (
            "provides_capabilities",
            "requires_capabilities",
            "evaluation_suites",
        ):
            data[field] = tuple(data.get(field) or ())
        return NeuronSpecification(**data)

    @staticmethod
    def _append_history(
        conn: sqlite3.Connection,
        neuron_id: str,
        version: str,
        action: str,
        payload: dict[str, Any],
    ) -> None:
        conn.execute(
            """INSERT INTO neuron_specification_history
            (neuron_id, version, action, payload_json)
            VALUES (?, ?, ?, ?)""",
            (neuron_id, version, action, json.dumps(payload, sort_keys=True)),
        )

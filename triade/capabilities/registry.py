"""Registro persistente de capacidades."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

VALID_STATES = {"experimental", "active", "deprecated", "blocked"}


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    capability_id: str
    name: str
    domain: str
    version: str
    owner: str
    component: str
    state: str = "experimental"
    critical: bool = False
    dependencies: tuple[str, ...] = ()
    evaluation_suites: tuple[str, ...] = ()
    rollback_policy: str | None = None

    def validate(self) -> None:
        required = (self.capability_id, self.name, self.domain, self.version, self.owner, self.component)
        if not all(value.strip() for value in required):
            raise ValueError("campos obligatorios incompletos")
        if self.state not in VALID_STATES:
            raise ValueError(f"estado inválido: {self.state}")
        if self.capability_id in self.dependencies:
            raise ValueError("dependencia circular directa")
        if self.critical and (not self.evaluation_suites or not self.rollback_policy):
            raise ValueError("capacidad crítica requiere suite y rollback")


class CapabilityRegistry:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS capability_registry (
                    capability_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (capability_id, version)
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def register(self, definition: CapabilityDefinition) -> dict[str, Any]:
        definition.validate()
        missing = [dep for dep in definition.dependencies if self.get(dep) is None]
        if missing:
            raise ValueError(f"dependencias inexistentes: {', '.join(sorted(missing))}")
        payload = asdict(definition)
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO capability_registry VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                    (definition.capability_id, definition.version, json.dumps(payload, sort_keys=True), definition.state),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("capacidad ya registrada") from exc
        return payload

    def get(self, capability_id: str, version: str | None = None) -> dict[str, Any] | None:
        sql = "SELECT payload_json FROM capability_registry WHERE capability_id = ?"
        params: list[Any] = [capability_id]
        if version:
            sql += " AND version = ?"
            params.append(version)
        sql += " ORDER BY created_at DESC, version DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def list(self, *, state: str | None = None, domain: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM capability_registry ORDER BY capability_id, version").fetchall()
        items = [json.loads(row["payload_json"]) for row in rows]
        if state:
            items = [item for item in items if item["state"] == state]
        if domain:
            items = [item for item in items if item["domain"] == domain]
        return items

    def set_state(self, capability_id: str, version: str, state: str) -> dict[str, Any]:
        if state not in VALID_STATES:
            raise ValueError(f"estado inválido: {state}")
        item = self.get(capability_id, version)
        if item is None:
            raise KeyError(f"capacidad no registrada: {capability_id}@{version}")
        item["state"] = state
        with self._connect() as conn:
            conn.execute(
                "UPDATE capability_registry SET payload_json = ?, state = ? WHERE capability_id = ? AND version = ?",
                (json.dumps(item, sort_keys=True), state, capability_id, version),
            )
        return item

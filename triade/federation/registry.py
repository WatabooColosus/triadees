"""Registro local, deny-by-default, para nodos federados de Tríade."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

NodeState = Literal["pending", "trusted", "quarantined", "revoked"]
VALID_STATES = {"pending", "trusted", "quarantined", "revoked"}
VALID_PERMISSIONS = {"discover", "submit_work", "return_evidence", "read_public_capabilities"}


@dataclass(frozen=True, slots=True)
class FederatedNodeIdentity:
    node_id: str
    display_name: str
    endpoint: str
    public_key: str
    capabilities: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    state: NodeState = "pending"
    trust_score: float = 0.0

    def __post_init__(self) -> None:
        if not all((self.node_id.strip(), self.display_name.strip(), self.endpoint.strip(), self.public_key.strip())):
            raise ValueError("node_id, display_name, endpoint y public_key son obligatorios")
        if self.state not in VALID_STATES:
            raise ValueError("state inválido")
        if not 0.0 <= float(self.trust_score) <= 1.0:
            raise ValueError("trust_score debe estar entre 0 y 1")
        unknown = set(self.permissions) - VALID_PERMISSIONS
        if unknown:
            raise ValueError(f"permisos desconocidos: {', '.join(sorted(unknown))}")
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("capabilities contiene duplicados")
        if len(self.permissions) != len(set(self.permissions)):
            raise ValueError("permissions contiene duplicados")

    @property
    def key_fingerprint(self) -> str:
        normalized = self.public_key.strip().encode("utf-8")
        return hashlib.sha256(normalized).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["key_fingerprint"] = self.key_fingerprint
        return payload


class FederatedNodeRegistry:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS federated_nodes_v2 (
                    node_id TEXT PRIMARY KEY,
                    key_fingerprint TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL,
                    trust_score REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS federated_node_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_federated_nodes_state
                    ON federated_nodes_v2(state, trust_score);
                CREATE INDEX IF NOT EXISTS idx_federated_node_events
                    ON federated_node_events(node_id, id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def register(self, identity: FederatedNodeIdentity, *, actor: str = "local-system") -> dict[str, Any]:
        payload = identity.to_dict()
        with self._connect() as conn:
            try:
                conn.execute(
                    """INSERT INTO federated_nodes_v2
                    (node_id, key_fingerprint, state, trust_score, payload_json)
                    VALUES (?, ?, ?, ?, ?)""",
                    (
                        identity.node_id,
                        identity.key_fingerprint,
                        identity.state,
                        identity.trust_score,
                        json.dumps(payload, sort_keys=True),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("node_id o clave pública ya registrados") from exc
            self._event(conn, identity.node_id, "registered", actor, "registro inicial", payload)
        return payload

    def get(self, node_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM federated_nodes_v2 WHERE node_id = ?",
                (node_id,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def transition(
        self,
        node_id: str,
        state: NodeState,
        *,
        actor: str,
        reason: str,
        trust_score: float | None = None,
    ) -> dict[str, Any]:
        if state not in VALID_STATES:
            raise ValueError("state inválido")
        if not actor.strip() or not reason.strip():
            raise ValueError("actor y reason son obligatorios")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json, state, trust_score FROM federated_nodes_v2 WHERE node_id = ?",
                (node_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"nodo no registrado: {node_id}")
            current = str(row["state"])
            allowed = {
                "pending": {"trusted", "quarantined", "revoked"},
                "trusted": {"quarantined", "revoked"},
                "quarantined": {"pending", "trusted", "revoked"},
                "revoked": set(),
            }
            if state not in allowed[current]:
                raise ValueError(f"transición inválida: {current} -> {state}")
            score = float(row["trust_score"] if trust_score is None else trust_score)
            if not 0.0 <= score <= 1.0:
                raise ValueError("trust_score debe estar entre 0 y 1")
            if state == "trusted" and score < 0.5:
                raise ValueError("un nodo trusted requiere trust_score >= 0.5")
            payload = json.loads(row["payload_json"])
            payload["state"] = state
            payload["trust_score"] = score
            conn.execute(
                """UPDATE federated_nodes_v2
                SET state = ?, trust_score = ?, payload_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE node_id = ?""",
                (state, score, json.dumps(payload, sort_keys=True), node_id),
            )
            self._event(conn, node_id, f"state:{state}", actor, reason, payload)
        return payload

    def authorize(self, node_id: str, *, capability: str, permission: str) -> bool:
        if permission not in VALID_PERMISSIONS:
            return False
        node = self.get(node_id)
        if node is None or node["state"] != "trusted" or float(node["trust_score"]) < 0.5:
            return False
        return capability in node["capabilities"] and permission in node["permissions"]

    def history(self, node_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT action, actor, reason, payload_json, created_at
                FROM federated_node_events WHERE node_id = ? ORDER BY id""",
                (node_id,),
            ).fetchall()
        return [
            {
                "action": row["action"],
                "actor": row["actor"],
                "reason": row["reason"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    @staticmethod
    def _event(
        conn: sqlite3.Connection,
        node_id: str,
        action: str,
        actor: str,
        reason: str,
        payload: dict[str, Any],
    ) -> None:
        conn.execute(
            """INSERT INTO federated_node_events
            (node_id, action, actor, reason, payload_json)
            VALUES (?, ?, ?, ?, ?)""",
            (node_id, action, actor, reason, json.dumps(payload, sort_keys=True)),
        )

"""Tool registry integration for neuron_factory: permite que las neuronas
accedan a herramientas registradas y sus contratos de seguridad."""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    import hashlib
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS neuron_tool_bindings (
    binding_id     TEXT PRIMARY KEY,
    neuron_id      TEXT NOT NULL,
    tool_id        TEXT NOT NULL,
    permissions_json TEXT DEFAULT '[]',
    risk_level     TEXT DEFAULT 'low',
    max_invocations INTEGER DEFAULT 100,
    invocations    INTEGER DEFAULT 0,
    enabled        INTEGER DEFAULT 1,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ntbr_neuron ON neuron_tool_bindings(neuron_id);
"""


class NeuronToolBindings:
    """Gestiona las herramientas disponibles para cada neurona y sus permisos."""

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def bind_tool(self, neuron_id: str, tool_id: str,
                  permissions: list[str] | None = None,
                  risk_level: str = "low",
                  max_invocations: int = 100) -> dict:
        binding_id = _gen_id("ntbind")
        self._conn.execute(
            """INSERT INTO neuron_tool_bindings
               (binding_id, neuron_id, tool_id, permissions_json,
                risk_level, max_invocations, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (binding_id, neuron_id, tool_id,
             json.dumps(permissions or ["read"], default=str),
             risk_level, max_invocations, utc_now()),
        )
        self._conn.commit()
        return {"binding_id": binding_id, "neuron_id": neuron_id, "tool_id": tool_id}

    def can_invoke(self, neuron_id: str, tool_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM neuron_tool_bindings WHERE neuron_id=? AND tool_id=? AND enabled=1",
            (neuron_id, tool_id),
        ).fetchone()
        if not row:
            return {"allowed": False, "reason": "no_binding"}
        if row["invocations"] >= row["max_invocations"]:
            return {"allowed": False, "reason": "quota_exceeded",
                    "invocations": row["invocations"], "max": row["max_invocations"]}
        return {"allowed": True, "permissions": json.loads(row["permissions_json"]),
                "risk_level": row["risk_level"]}

    def record_invocation(self, neuron_id: str, tool_id: str) -> dict:
        self._conn.execute(
            """UPDATE neuron_tool_bindings
               SET invocations = invocations + 1
               WHERE neuron_id=? AND tool_id=?""",
            (neuron_id, tool_id),
        )
        self._conn.commit()
        return {"neuron_id": neuron_id, "tool_id": tool_id, "invoked": True}

    def unbind_tool(self, neuron_id: str, tool_id: str) -> dict:
        self._conn.execute(
            "DELETE FROM neuron_tool_bindings WHERE neuron_id=? AND tool_id=?",
            (neuron_id, tool_id),
        )
        self._conn.commit()
        return {"neuron_id": neuron_id, "tool_id": tool_id, "unbound": True}

    def neuron_tools(self, neuron_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM neuron_tool_bindings WHERE neuron_id=?", (neuron_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def bindings_for_tool(self, tool_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM neuron_tool_bindings WHERE tool_id=?", (tool_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def doctor(self) -> dict:
        total = self._conn.execute("SELECT COUNT(*) as c FROM neuron_tool_bindings").fetchone()["c"]
        enabled = self._conn.execute("SELECT COUNT(*) as c FROM neuron_tool_bindings WHERE enabled=1").fetchone()["c"]
        return {"total_bindings": total, "enabled": enabled}

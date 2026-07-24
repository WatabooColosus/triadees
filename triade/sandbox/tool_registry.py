"""Registro tipado de herramientas con ejecución segura.

Todas las herramientas se registran con contratos de entrada/salida,
categorías y permisos. La ejecución NUNCA usa shell=True.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from triade.core.contracts import utc_now

ToolCategory = Literal["analysis", "memory", "code", "system", "federation"]
ToolPermission = Literal["read", "write", "execute", "network"]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    tool_id: str
    name: str
    category: ToolCategory
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    permissions: tuple[ToolPermission, ...]
    timeout_seconds: int = 30
    max_memory_mb: int = 256
    sandbox_required: bool = True
    version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    tool_id: str
    success: bool
    output: Any
    error: str | None
    duration_ms: float
    executed_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ToolRegistry:
    """Registro central de herramientas tipadas."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self._tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS tool_registry (
                    tool_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    input_schema_json TEXT NOT NULL,
                    output_schema_json TEXT NOT NULL,
                    permissions_json TEXT NOT NULL,
                    timeout_seconds INTEGER NOT NULL DEFAULT 30,
                    max_memory_mb INTEGER NOT NULL DEFAULT 256,
                    sandbox_required INTEGER NOT NULL DEFAULT 1,
                    version TEXT NOT NULL DEFAULT '1.0.0',
                    registered_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS tool_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_id TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    output_preview TEXT,
                    error TEXT,
                    duration_ms REAL NOT NULL,
                    executed_at TEXT NOT NULL
                )"""
            )

    def register(self, definition: ToolDefinition) -> None:
        self._tools[definition.tool_id] = definition
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO tool_registry
                (tool_id, name, category, description, input_schema_json, output_schema_json,
                 permissions_json, timeout_seconds, max_memory_mb, sandbox_required, version, registered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    definition.tool_id, definition.name, definition.category,
                    definition.description,
                    json.dumps(definition.input_schema, ensure_ascii=False),
                    json.dumps(definition.output_schema, ensure_ascii=False),
                    json.dumps(list(definition.permissions), ensure_ascii=False),
                    definition.timeout_seconds, definition.max_memory_mb,
                    1 if definition.sandbox_required else 0,
                    definition.version, utc_now(),
                ),
            )

    def register_handler(self, tool_id: str, handler: Callable[..., Any]) -> None:
        self._handlers[tool_id] = handler

    def get(self, tool_id: str) -> ToolDefinition | None:
        if tool_id in self._tools:
            return self._tools[tool_id]
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tool_registry WHERE tool_id = ?", (tool_id,)
            ).fetchone()
        if row is None:
            return None
        return ToolDefinition(
            tool_id=row["tool_id"],
            name=row["name"],
            category=row["category"],
            description=row["description"],
            input_schema=json.loads(row["input_schema_json"]),
            output_schema=json.loads(row["output_schema_json"]),
            permissions=tuple(json.loads(row["permissions_json"])),
            timeout_seconds=row["timeout_seconds"],
            max_memory_mb=row["max_memory_mb"],
            sandbox_required=bool(row["sandbox_required"]),
            version=row["version"],
        )

    def list_tools(self, category: ToolCategory | None = None) -> list[ToolDefinition]:
        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT tool_id FROM tool_registry WHERE category = ?", (category,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT tool_id FROM tool_registry").fetchall()
        return [self.get(r["tool_id"]) for r in rows if self.get(r["tool_id"])]

    def validate_input(self, tool_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        definition = self.get(tool_id)
        if definition is None:
            return {"valid": False, "error": f"Herramienta '{tool_id}' no registrada."}
        schema = definition.input_schema
        required_fields = schema.get("required", [])
        missing = [f for f in required_fields if f not in payload]
        if missing:
            return {"valid": False, "error": f"Campos requeridos faltantes: {missing}"}
        return {"valid": True, "error": None}

    def execute(self, tool_id: str, payload: dict[str, Any]) -> ToolExecutionResult:
        import time
        start = time.perf_counter()
        validation = self.validate_input(tool_id, payload)
        if not validation["valid"]:
            return ToolExecutionResult(
                tool_id=tool_id, success=False, output=None,
                error=validation["error"], duration_ms=0, executed_at=utc_now(),
            )
        handler = self._handlers.get(tool_id)
        if handler is None:
            return ToolExecutionResult(
                tool_id=tool_id, success=False, output=None,
                error=f"No hay handler registrado para '{tool_id}'.",
                duration_ms=0, executed_at=utc_now(),
            )
        try:
            output = handler(payload)
            duration = (time.perf_counter() - start) * 1000
            result = ToolExecutionResult(
                tool_id=tool_id, success=True, output=output,
                error=None, duration_ms=round(duration, 2), executed_at=utc_now(),
            )
        except Exception as exc:
            duration = (time.perf_counter() - start) * 1000
            result = ToolExecutionResult(
                tool_id=tool_id, success=False, output=None,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=round(duration, 2), executed_at=utc_now(),
            )
        self._log_execution(result)
        return result

    def _log_execution(self, result: ToolExecutionResult) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO tool_executions(tool_id, success, output_preview, error, duration_ms, executed_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (result.tool_id, 1 if result.success else 0,
                     str(result.output)[:500] if result.output else None,
                     result.error, result.duration_ms, result.executed_at),
                )
        except sqlite3.OperationalError:
            pass

    def doctor(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) as c FROM tool_registry").fetchone()["c"]
            recent = conn.execute(
                "SELECT tool_id, SUM(CASE WHEN success THEN 1 ELSE 0 END) as ok, COUNT(*) as total FROM tool_executions GROUP BY tool_id"
            ).fetchall()
        return {
            "registered_tools": total,
            "handlers_loaded": len(self._handlers),
            "execution_stats": {r["tool_id"]: {"ok": r["ok"], "total": r["total"]} for r in recent},
        }

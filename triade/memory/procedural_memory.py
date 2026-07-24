"""Procedural Memory: conocimiento procedimental (cómo hacer cosas).

Almacena secuencias de pasos, recetas, workflows y patrones de ejecución.
Se distingue de la memoria declarativa (qué sé) por enfocarse en procesos.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now


@dataclass(slots=True)
class Procedure:
    procedure_id: str = ""
    name: str = ""
    description: str = ""
    category: str = "general"
    steps: list[dict[str, Any]] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    success_count: int = 0
    failure_count: int = 0
    confidence: float = 0.5
    source: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "procedure_id": self.procedure_id, "name": self.name,
            "description": self.description, "category": self.category,
            "steps": list(self.steps), "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "success_count": self.success_count, "failure_count": self.failure_count,
            "confidence": round(self.confidence, 4), "source": self.source,
            "tags": list(self.tags), "created_at": self.created_at, "updated_at": self.updated_at,
        }

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / max(1, total)


class ProceduralMemory:
    """Gestor de memoria procedimental (procedimientos ejecutables)."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def add_procedure(
        self,
        *,
        name: str,
        description: str = "",
        category: str = "general",
        steps: list[dict[str, Any]] | None = None,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        source: str = "",
        tags: list[str] | None = None,
    ) -> Procedure:
        import uuid
        proc_id = f"proc-{uuid.uuid4().hex[:12]}"
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO procedural_memory
                (procedure_id, name, description, category, steps, input_schema, output_schema,
                 success_count, failure_count, confidence, source, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0.5, ?, ?, ?, ?)""",
                (proc_id, name, description, category,
                 json.dumps(steps or [], ensure_ascii=False),
                 json.dumps(input_schema or {}, ensure_ascii=False),
                 json.dumps(output_schema or {}, ensure_ascii=False),
                 source, json.dumps(tags or [], ensure_ascii=False), now, now),
            )
        return Procedure(
            procedure_id=proc_id, name=name, description=description,
            category=category, steps=steps or [], source=source,
            tags=tags or [], created_at=now, updated_at=now,
        )

    def get(self, procedure_id: str) -> Procedure | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM procedural_memory WHERE procedure_id = ?", (procedure_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_procedure(row)

    def record_execution(self, procedure_id: str, success: bool) -> Procedure | None:
        now = utc_now()
        field = "success_count" if success else "failure_count"
        with self._connect() as conn:
            conn.execute(
                f"UPDATE procedural_memory SET {field} = {field} + 1, updated_at = ? WHERE procedure_id = ?",
                (now, procedure_id),
            )
            row = conn.execute(
                "SELECT * FROM procedural_memory WHERE procedure_id = ?", (procedure_id,)
            ).fetchone()
            if row is None:
                return None
            total = int(row["success_count"]) + int(row["failure_count"])
            new_conf = min(1.0, int(row["success_count"]) / max(1, total))
            conn.execute(
                "UPDATE procedural_memory SET confidence = ? WHERE procedure_id = ?",
                (round(new_conf, 4), procedure_id),
            )
        return self.get(procedure_id)

    def list_by_category(self, category: str, limit: int = 50) -> list[Procedure]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM procedural_memory WHERE category = ? ORDER BY confidence DESC LIMIT ?",
                (category, limit),
            ).fetchall()
        return [self._row_to_procedure(r) for r in rows]

    def list_by_tag(self, tag: str, limit: int = 50) -> list[Procedure]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM procedural_memory WHERE tags LIKE ? ORDER BY confidence DESC LIMIT ?",
                (f"%{tag}%", limit),
            ).fetchall()
        return [self._row_to_procedure(r) for r in rows]

    def search(self, query: str, limit: int = 10) -> list[Procedure]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM procedural_memory
                WHERE name LIKE ? OR description LIKE ? OR tags LIKE ?
                ORDER BY confidence DESC LIMIT ?""",
                (f"%{query}%", f"%{query}%", f"%{query}%", limit),
            ).fetchall()
        return [self._row_to_procedure(r) for r in rows]

    def summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) as c FROM procedural_memory").fetchone()["c"]
            cats = conn.execute(
                "SELECT category, COUNT(*) as c FROM procedural_memory GROUP BY category"
            ).fetchall()
            avg_conf = conn.execute("SELECT AVG(confidence) as a FROM procedural_memory").fetchone()
        return {
            "total_procedures": count,
            "by_category": {r["category"]: r["c"] for r in cats},
            "avg_confidence": round(float(avg_conf["a"] or 0), 4),
        }

    @staticmethod
    def _row_to_procedure(row: sqlite3.Row) -> Procedure:
        def _json(raw: str, default: Any) -> Any:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return default
        return Procedure(
            procedure_id=str(row["procedure_id"]), name=str(row["name"]),
            description=str(row["description"] or ""),
            category=str(row["category"] or "general"),
            steps=_json(row["steps"], []),
            input_schema=_json(row["input_schema"], {}),
            output_schema=_json(row["output_schema"], {}),
            success_count=int(row["success_count"] or 0),
            failure_count=int(row["failure_count"] or 0),
            confidence=float(row["confidence"] or 0.5),
            source=str(row["source"] or ""),
            tags=_json(row["tags"], []),
            created_at=str(row["created_at"] or ""),
            updated_at=str(row["updated_at"] or ""),
        )

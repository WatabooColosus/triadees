"""Auto-modelo dinámico — identidad que evoluciona con la experiencia.

Mientras identity_core permanece intocable (misión/ética fundacional),
auto_identity almacena rasgos descubiertos por Tríade sobre sí misma:
capacidades, preferencias, patrones de comportamiento.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def new_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


DISCOVERY_CATEGORIES = {"capability", "preference", "behavior", "discovered_mission", "observed_pattern"}


class AutoIdentityStore:
    """Rasgos de identidad descubiertos por Tríade durante su operación."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.schema_path = Path("triade/memory/schemas.sql")
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        if not self.schema_path.exists():
            raise FileNotFoundError(f"No existe el esquema de memoria: {self.schema_path}")
        with self._connect() as conn:
            conn.executescript(self.schema_path.read_text(encoding="utf-8"))

    def add_or_update(
        self,
        trait_key: str,
        trait_value: str,
        category: str = "discovered",
        source_ref: str | None = None,
        confidence: float | None = None,
    ) -> dict[str, Any]:
        now = new_utc()
        category = category if category in DISCOVERY_CATEGORIES else "discovered"
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, confidence, evidence_count FROM auto_identity WHERE trait_key = ?",
                (trait_key,),
            ).fetchone()

            if existing:
                new_confidence = confidence if confidence is not None else min(1.0, float(existing["confidence"]) + 0.05)
                new_evidence = int(existing["evidence_count"]) + 1
                conn.execute(
                    """UPDATE auto_identity
                    SET trait_value = ?, category = ?, source_ref = ?,
                        confidence = ?, evidence_count = ?, updated_at = ?
                    WHERE id = ?""",
                    (trait_value, category, source_ref, new_confidence, new_evidence, now, int(existing["id"])),
                )
                return {"key": trait_key, "updated": True, "confidence": new_confidence, "evidence_count": new_evidence}

            final_confidence = confidence if confidence is not None else 0.3
            conn.execute(
                """INSERT INTO auto_identity
                (trait_key, trait_value, category, source_ref, confidence, status, evidence_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'candidate', 1, ?, ?)""",
                (trait_key, trait_value, category, source_ref, final_confidence, now, now),
            )
            return {"key": trait_key, "updated": False, "confidence": final_confidence, "evidence_count": 1}

    def archive(self, trait_key: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE auto_identity SET status = 'archived', updated_at = ? WHERE trait_key = ? AND status != 'archived'",
                (new_utc(), trait_key),
            )
            return cursor.rowcount > 0

    def promote(self, trait_key: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE auto_identity SET status = 'stable', updated_at = ? WHERE trait_key = ? AND status = 'candidate'",
                (new_utc(), trait_key),
            )
            return cursor.rowcount > 0

    def load_active(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT trait_key, trait_value, category, source_ref, confidence, evidence_count, status, created_at, updated_at
                FROM auto_identity WHERE status IN ('candidate', 'stable') ORDER BY confidence DESC, evidence_count DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def load_by_category(self, category: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT trait_key, trait_value, category, source_ref, confidence, evidence_count, status, created_at, updated_at
                FROM auto_identity WHERE category = ? AND status IN ('candidate', 'stable')
                ORDER BY confidence DESC""",
                (category,),
            ).fetchall()
        return [dict(row) for row in rows]

    def evolve_from_reflection(self, run_id: str, reflection_data: dict[str, Any]) -> list[dict[str, Any]]:
        evolved: list[dict[str, Any]] = []
        observations = reflection_data.get("observations", [])
        themes = reflection_data.get("learning_candidates", {}).get("candidate_themes", [])

        seen = set()
        for obs in observations:
            text = str(obs.get("observation", obs)) if isinstance(obs, dict) else str(obs)
            if len(text) < 20 or text in seen:
                continue
            seen.add(text)
            key = "observed_" + text.lower().replace(" ", "_")[:40]
            # Strip non-alphanumeric
            key = "".join(c if c.isalnum() or c == "_" else "" for c in key)
            if not key:
                continue
            result = self.add_or_update(
                trait_key=key,
                trait_value=text[:200],
                category="observed_pattern",
                source_ref=run_id,
                confidence=0.25,
            )
            if result:
                evolved.append(result)

        for theme in themes:
            name = str(theme.get("theme", theme)) if isinstance(theme, dict) else str(theme)
            if len(name) < 15 or name in seen:
                continue
            seen.add(name)
            key = "theme_" + name.lower().replace(" ", "_")[:40]
            key = "".join(c if c.isalnum() or c == "_" else "" for c in key)
            if not key:
                continue
            result = self.add_or_update(
                trait_key=key,
                trait_value=name[:200],
                category="discovered_mission",
                source_ref=run_id,
                confidence=0.2,
            )
            if result:
                evolved.append(result)

        return evolved

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM auto_identity WHERE status IN ('candidate', 'stable')").fetchone()
            return row["c"] if row else 0

    def count_all(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM auto_identity").fetchone()
            return row["c"] if row else 0

    def doctor(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "active_count": self.count(),
            "total_count": self.count_all(),
            "categories": self._category_counts(),
        }

    def _category_counts(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT category, COUNT(*) AS c FROM auto_identity WHERE status IN ('candidate', 'stable') GROUP BY category"
            ).fetchall()
        return {row["category"]: row["c"] for row in rows}

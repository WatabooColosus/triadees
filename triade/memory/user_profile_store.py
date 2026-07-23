"""Memoria personal explícita, persistente y aislada por principal."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now


_NAME_PATTERNS = (
    re.compile(r"\bme\s+llamo\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ' -]{0,58})", re.I),
    re.compile(r"\bmi\s+nombre\s+es\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ' -]{0,58})", re.I),
)


class UserProfileStore:
    """Conserva hechos que el usuario declaró expresamente sobre sí mismo."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS user_profile_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    principal_id TEXT NOT NULL,
                    fact_key TEXT NOT NULL,
                    fact_value TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    evidence_count INTEGER NOT NULL DEFAULT 1,
                    source_run TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(principal_id, fact_key)
                )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_user_profile_principal ON user_profile_memory(principal_id)")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def valid_principal(value: Any) -> str | None:
        clean = str(value or "").strip()
        return clean if 8 <= len(clean) <= 128 and re.fullmatch(r"[A-Za-z0-9._:-]+", clean) else None

    @staticmethod
    def extract_explicit_facts(text: str) -> dict[str, str]:
        for pattern in _NAME_PATTERNS:
            match = pattern.search(text or "")
            if match:
                name = re.split(r"[,.;!?\n]", match.group(1), maxsplit=1)[0].strip(" -")
                words = name.split()
                if 1 <= len(words) <= 5:
                    return {"preferred_name": " ".join(word.capitalize() for word in words)}
        return {}

    def capture(self, principal_id: Any, text: str, source_run: str) -> dict[str, Any]:
        principal = self.valid_principal(principal_id)
        facts = self.extract_explicit_facts(text)
        if not principal or not facts:
            return {"stored": False, "reason": "no_scoped_explicit_fact", "facts": {}}
        now = utc_now()
        with self._connect() as conn:
            for key, value in facts.items():
                conn.execute(
                    """INSERT INTO user_profile_memory
                       (principal_id, fact_key, fact_value, confidence, evidence_count, source_run, created_at, updated_at)
                       VALUES (?, ?, ?, 1.0, 1, ?, ?, ?)
                       ON CONFLICT(principal_id, fact_key) DO UPDATE SET
                         fact_value=excluded.fact_value,
                         confidence=1.0,
                         evidence_count=user_profile_memory.evidence_count + 1,
                         source_run=excluded.source_run,
                         updated_at=excluded.updated_at""",
                    (principal, key, value, source_run, now, now),
                )
        return {"stored": True, "facts": facts, "principal_scoped": True}

    def load(self, principal_id: Any) -> dict[str, str]:
        principal = self.valid_principal(principal_id)
        if not principal:
            return {}
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT fact_key, fact_value FROM user_profile_memory WHERE principal_id = ? ORDER BY id",
                (principal,),
            ).fetchall()
        return {str(row["fact_key"]): str(row["fact_value"]) for row in rows}


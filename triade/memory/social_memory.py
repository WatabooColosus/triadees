"""Social Memory: perfiles de usuario, relaciones e interacciones.

Almacena preferencias, historial de consultas, nivel de confianza
y contexto social del usuario. No almacena datos personales sensibles.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now


@dataclass(slots=True)
class UserProfile:
    user_id: str = ""
    display_name: str = ""
    language: str = "es"
    interaction_count: int = 0
    trust_level: float = 0.5
    preferences: dict[str, Any] = field(default_factory=dict)
    topics: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    last_seen_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id, "display_name": self.display_name,
            "language": self.language, "interaction_count": self.interaction_count,
            "trust_level": round(self.trust_level, 4), "preferences": dict(self.preferences),
            "topics": list(self.topics), "created_at": self.created_at,
            "last_seen_at": self.last_seen_at,
        }


@dataclass(slots=True)
class InteractionRecord:
    user_id: str = ""
    run_id: str = ""
    intent: str = ""
    topic: str = ""
    satisfaction: float = 0.5
    notes: str = ""
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id, "run_id": self.run_id, "intent": self.intent,
            "topic": self.topic, "satisfaction": round(self.satisfaction, 4),
            "notes": self.notes, "created_at": self.created_at,
        }


class SocialMemory:
    """Gestor de memoria social (user profiles + interactions)."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def upsert_profile(
        self,
        *,
        user_id: str,
        display_name: str = "",
        language: str = "es",
        preferences: dict[str, Any] | None = None,
        topics: list[str] | None = None,
    ) -> UserProfile:
        now = utc_now()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE user_profiles SET display_name = COALESCE(NULLIF(?, ''), display_name),
                    language = ?, preferences = ?, topics = ?, last_seen_at = ?, interaction_count = interaction_count + 1
                    WHERE user_id = ?""",
                    (display_name, language, json.dumps(preferences or {}), json.dumps(topics or [], ensure_ascii=False), now, user_id),
                )
            else:
                conn.execute(
                    """INSERT INTO user_profiles (user_id, display_name, language, trust_level, preferences, topics, created_at, last_seen_at, interaction_count)
                    VALUES (?, ?, ?, 0.5, ?, ?, ?, ?, 1)""",
                    (user_id, display_name, language, json.dumps(preferences or {}), json.dumps(topics or [], ensure_ascii=False), now, now),
                )
        return self.get_profile(user_id) or UserProfile(user_id=user_id, display_name=display_name)

    def get_profile(self, user_id: str) -> UserProfile | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                return None
            prefs = {}
            topics = []
            try:
                prefs = json.loads(str(row["preferences"] or "{}"))
            except (json.JSONDecodeError, TypeError):
                pass
            try:
                topics = json.loads(str(row["topics"] or "[]"))
            except (json.JSONDecodeError, TypeError):
                pass
            return UserProfile(
                user_id=str(row["user_id"]), display_name=str(row["display_name"] or ""),
                language=str(row["language"] or "es"),
                interaction_count=int(row["interaction_count"] or 0),
                trust_level=float(row["trust_level"] or 0.5),
                preferences=prefs, topics=topics,
                created_at=str(row["created_at"] or ""),
                last_seen_at=str(row["last_seen_at"] or ""),
            )

    def record_interaction(
        self,
        *,
        user_id: str,
        run_id: str,
        intent: str = "",
        topic: str = "",
        satisfaction: float = 0.5,
        notes: str = "",
    ) -> InteractionRecord:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO user_interactions (user_id, run_id, intent, topic, satisfaction, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, run_id, intent, topic, max(0, min(1, satisfaction)), notes, now),
            )
        return InteractionRecord(
            user_id=user_id, run_id=run_id, intent=intent, topic=topic,
            satisfaction=satisfaction, notes=notes, created_at=now,
        )

    def get_interactions(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM user_interactions WHERE user_id = ? ORDER BY rowid DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_trust(self, user_id: str, delta: float) -> float:
        profile = self.get_profile(user_id)
        if not profile:
            return 0.5
        new_trust = max(0, min(1, profile.trust_level + delta))
        with self._connect() as conn:
            conn.execute("UPDATE user_profiles SET trust_level = ? WHERE user_id = ?", (round(new_trust, 4), user_id))
        return new_trust

    def top_topics(self, user_id: str, limit: int = 5) -> list[str]:
        profile = self.get_profile(user_id)
        if not profile:
            return []
        topic_counts: dict[str, int] = {}
        interactions = self.get_interactions(user_id, limit=50)
        for inter in interactions:
            t = inter.get("topic", "")
            if t:
                topic_counts[t] = topic_counts.get(t, 0) + 1
        return sorted(topic_counts, key=topic_counts.get, reverse=True)[:limit]

    def summary(self, user_id: str | None = None) -> dict[str, Any]:
        with self._connect() as conn:
            if user_id:
                profile = conn.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
                count = conn.execute("SELECT COUNT(*) as c FROM user_interactions WHERE user_id = ?", (user_id,)).fetchone()
                return {
                    "user_id": user_id,
                    "has_profile": profile is not None,
                    "interaction_count": count["c"] if count else 0,
                }
            else:
                total_profiles = conn.execute("SELECT COUNT(*) as c FROM user_profiles").fetchone()["c"]
                total_interactions = conn.execute("SELECT COUNT(*) as c FROM user_interactions").fetchone()["c"]
                return {"total_profiles": total_profiles, "total_interactions": total_interactions}

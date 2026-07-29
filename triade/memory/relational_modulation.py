"""Estado funcional PV-7 por sesión, sin afirmar experiencia subjetiva."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

SCHEMA = Path(__file__).resolve().parent / "schemas.sql"
MIGRATION = Path(__file__).resolve().parent / "migrations/022_relational_modulation.sql"
PV7_KEYS = (
    "humildad",
    "generosidad",
    "respeto",
    "paciencia",
    "templanza",
    "caridad",
    "diligencia",
)
DEFAULT_BASELINE = {
    "humildad": 0.70,
    "generosidad": 0.70,
    "respeto": 0.80,
    "paciencia": 0.70,
    "templanza": 0.70,
    "caridad": 0.70,
    "diligencia": 0.80,
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load(raw: str) -> dict[str, float]:
    data = json.loads(raw)
    return {key: float(data[key]) for key in PV7_KEYS}


class RelationalModulationStore:
    """Persiste modulación relacional; no representa sentimientos humanos."""

    EVENT_LIMITS: ClassVar[dict[str, float]] = {
        "supportive_interaction": 0.08,
        "user_correction": 0.10,
        "conflict_signal": 0.12,
        "task_success": 0.06,
        "task_failure": 0.08,
        "safety_intervention": 0.12,
        "time_decay": 0.25,
    }

    def __init__(self, db_path: str | Path, max_deviation: float = 0.25) -> None:
        if not 0 < max_deviation <= 0.5:
            raise ValueError("max_deviation debe estar en (0, 0.5]")
        self.db_path = Path(db_path)
        self.max_deviation = max_deviation
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA.read_text(encoding="utf-8"))
            conn.executescript(MIGRATION.read_text(encoding="utf-8"))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _scope(user_id: str, session_id: str) -> tuple[str, str]:
        user, session = user_id.strip(), session_id.strip()
        if not user or not session:
            raise ValueError("user_id y session_id son obligatorios")
        return user, session

    def initialize(
        self,
        user_id: str,
        session_id: str,
        baseline: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        user, session = self._scope(user_id, session_id)
        values = dict(DEFAULT_BASELINE if baseline is None else baseline)
        if set(values) != set(PV7_KEYS):
            raise ValueError("baseline debe contener exactamente PV-7")
        values = {key: max(0.0, min(1.0, float(values[key]))) for key in PV7_KEYS}
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO relational_modulation_states
                (user_id, session_id, baseline_json, state_json, updated_at)
                VALUES (?, ?, ?, ?, ?)""",
                (user, session, json.dumps(values), json.dumps(values), now),
            )
        return self.get(user, session)

    def get(self, user_id: str, session_id: str) -> dict[str, Any]:
        user, session = self._scope(user_id, session_id)
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM relational_modulation_states
                WHERE user_id = ? AND session_id = ?""",
                (user, session),
            ).fetchone()
        if row is None:
            return self.initialize(user, session)
        return {
            "state_type": "relational modulation state",
            "user_id": user,
            "session_id": session,
            "baseline": _load(str(row["baseline_json"])),
            "pv7": _load(str(row["state_json"])),
            "event_count": int(row["event_count"]),
            "last_event_at": row["last_event_at"],
            "updated_at": str(row["updated_at"]),
            "subjective_emotion_claimed": False,
        }

    def apply_event(
        self,
        user_id: str,
        session_id: str,
        event_type: str,
        delta: dict[str, float],
        *,
        source_ref: str,
        explanation: str,
        at: str | None = None,
    ) -> dict[str, Any]:
        if event_type not in self.EVENT_LIMITS:
            raise ValueError(f"event_type no gobernado: {event_type}")
        if not source_ref.strip() or not explanation.strip():
            raise ValueError("source_ref y explanation son obligatorios")
        unknown = set(delta) - set(PV7_KEYS)
        if unknown:
            raise ValueError(f"Dimensiones PV-7 desconocidas: {sorted(unknown)}")
        current = self.get(user_id, session_id)
        user, session = current["user_id"], current["session_id"]
        baseline, before = current["baseline"], current["pv7"]
        limit = self.EVENT_LIMITS[event_type]
        requested = {key: float(delta.get(key, 0.0)) for key in PV7_KEYS}
        after: dict[str, float] = {}
        applied: dict[str, float] = {}
        for key in PV7_KEYS:
            bounded_delta = max(-limit, min(limit, requested[key]))
            low = max(0.0, baseline[key] - self.max_deviation)
            high = min(1.0, baseline[key] + self.max_deviation)
            after[key] = round(max(low, min(high, before[key] + bounded_delta)), 6)
            applied[key] = round(after[key] - before[key], 6)
        event_id, timestamp = f"rme-{uuid.uuid4().hex}", at or _now()
        with self._connect() as conn:
            conn.execute(
                """UPDATE relational_modulation_states SET state_json = ?,
                event_count = event_count + 1, last_event_at = ?, updated_at = ?
                WHERE user_id = ? AND session_id = ?""",
                (json.dumps(after), timestamp, timestamp, user, session),
            )
            conn.execute(
                """INSERT INTO relational_modulation_events
                (event_id, user_id, session_id, event_type, before_json,
                 requested_delta_json, applied_delta_json, after_json,
                 explanation, source_ref, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id,
                    user,
                    session,
                    event_type,
                    json.dumps(before),
                    json.dumps(requested),
                    json.dumps(applied),
                    json.dumps(after),
                    explanation,
                    source_ref,
                    timestamp,
                ),
            )
        return {
            "event_id": event_id,
            "event_type": event_type,
            "before": before,
            "requested_delta": requested,
            "applied_delta": applied,
            "after": after,
            "explanation": explanation,
            "source_ref": source_ref,
            "limits_applied": True,
        }

    def decay(
        self,
        user_id: str,
        session_id: str,
        *,
        elapsed_seconds: float,
        half_life_seconds: float = 3600.0,
    ) -> dict[str, Any]:
        if elapsed_seconds < 0 or half_life_seconds <= 0:
            raise ValueError("Los tiempos de decay deben ser válidos")
        current = self.get(user_id, session_id)
        factor = math.pow(0.5, elapsed_seconds / half_life_seconds)
        delta = {
            key: (current["baseline"][key] - current["pv7"][key]) * (1.0 - factor)
            for key in PV7_KEYS
        }
        return self.apply_event(
            user_id,
            session_id,
            "time_decay",
            delta,
            source_ref=f"decay:{elapsed_seconds}:{half_life_seconds}",
            explanation="Time decay moved relational modulation toward session baseline.",
        )

    def rollback_event(
        self, event_id: str, *, actor: str, reason: str
    ) -> dict[str, Any]:
        if not actor.strip() or not reason.strip():
            raise ValueError("actor y reason son obligatorios")
        with self._connect() as conn:
            event = conn.execute(
                "SELECT * FROM relational_modulation_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if event is None:
                raise KeyError(event_id)
            if int(event["rolled_back"]):
                raise ValueError("El evento ya fue revertido")
            latest = conn.execute(
                """SELECT event_id FROM relational_modulation_events
                WHERE user_id = ? AND session_id = ? AND rolled_back = 0
                ORDER BY created_at DESC, rowid DESC LIMIT 1""",
                (event["user_id"], event["session_id"]),
            ).fetchone()
            if latest is None or latest["event_id"] != event_id:
                raise ValueError("Solo el último evento activo puede revertirse")
            before = _load(str(event["before_json"]))
            conn.execute(
                """UPDATE relational_modulation_states SET state_json = ?,
                event_count = MAX(event_count - 1, 0), updated_at = ?
                WHERE user_id = ? AND session_id = ?""",
                (json.dumps(before), _now(), event["user_id"], event["session_id"]),
            )
            conn.execute(
                """UPDATE relational_modulation_events SET rolled_back = 1,
                explanation = explanation || ? WHERE event_id = ?""",
                (f" | rollback:{actor}:{reason}", event_id),
            )
        return {"event_id": event_id, "status": "rolled_back", "restored": before}

    def fingerprint(self) -> str:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT user_id, session_id, baseline_json, state_json,
                event_count, last_event_at FROM relational_modulation_states
                ORDER BY user_id, session_id"""
            ).fetchall()
        raw = json.dumps([dict(row) for row in rows], sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def backup(self, target: str | Path) -> dict[str, str]:
        destination = Path(target)
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as source, sqlite3.connect(destination) as dest:
            source.backup(dest)
        return {"path": str(destination), "fingerprint": self.fingerprint()}

    @classmethod
    def restore_to_sandbox(
        cls, backup: str | Path, target: str | Path, fingerprint: str
    ) -> dict[str, Any]:
        destination = Path(target)
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, destination)
        restored = cls(destination)
        current = restored.fingerprint()
        with sqlite3.connect(destination) as conn:
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        return {
            "status": "verified"
            if integrity == "ok" and current == fingerprint
            else "failed",
            "sqlite_integrity": integrity,
            "fingerprint": current,
            "production_overwritten": False,
        }

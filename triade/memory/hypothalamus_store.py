"""Almacenamiento persistente del estado emocional del Hipotálamo.

Cada run produce un estado emocional (VAD + fatiga) que persiste
en hypothalamus_state. El mood actual es siempre el último registro.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from triade.core.contracts import SignalPacket


@dataclass
class EmotionalState:
    valence: float = 0.1
    arousal: float = 0.0
    dominance: float = 0.2
    primary_emotion: str = "neutral"
    fatigue: float = 0.0
    pv7_baseline: dict[str, float] = field(default_factory=lambda: {
        "humildad": 0.7, "generosidad": 0.7, "respeto": 0.8,
        "paciencia": 0.7, "templanza": 0.7, "caridad": 0.7, "diligencia": 0.8,
    })
    run_count: int = 0
    last_active_at: str | None = None
    # PV-14: Señales de hardware y carga cognitiva
    cpu_load: float = 0.0
    ram_usage: float = 0.0
    gpu_utilization: float = 0.0
    gpu_memory_used: float = 0.0
    gpu_temperature: int = 0
    cognitive_load: float = 0.0
    curiosity: float = 0.0
    uncertainty: float = 0.0
    tensions: dict[str, float] = field(default_factory=dict)
    cognitive_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valence": self.valence,
            "arousal": self.arousal,
            "dominance": self.dominance,
            "primary_emotion": self.primary_emotion,
            "fatigue": self.fatigue,
            "pv7_baseline": dict(self.pv7_baseline),
            "run_count": self.run_count,
            "last_active_at": self.last_active_at,
            "cpu_load": self.cpu_load,
            "ram_usage": self.ram_usage,
            "gpu_utilization": self.gpu_utilization,
            "gpu_memory_used": self.gpu_memory_used,
            "gpu_temperature": self.gpu_temperature,
            "cognitive_load": self.cognitive_load,
            "curiosity": self.curiosity,
            "uncertainty": self.uncertainty,
            "tensions": dict(self.tensions),
            "cognitive_snapshot": dict(self.cognitive_snapshot),
        }


def new_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_primary_emotion(valence: float, arousal: float, fatigue: float) -> str:
    if fatigue > 0.7:
        return "fatigued"
    if arousal > 0.5 and valence > 0.3:
        return "engaged"
    if arousal > 0.5 and valence < -0.3:
        return "anxious"
    if arousal < -0.3 and valence > 0.3:
        return "calm"
    if arousal < -0.3 and valence < -0.3:
        return "withdrawn"
    if valence > 0.3:
        return "positive"
    if valence < -0.3:
        return "cautious"
    return "neutral"


def mood_from_signals(signals: SignalPacket, previous: EmotionalState | None = None) -> EmotionalState:
    prev = previous or EmotionalState()

    valence_tones = {"constructive": 0.2, "positive": 0.3, "encouraging": 0.3,
                     "supportive": 0.2, "neutral": 0.0, "cautious": -0.2,
                     "critical": -0.3, "warning": -0.3, "urgent": -0.1}
    tone_valence = valence_tones.get(signals.tone.lower(), 0.0)

    pv7_avg = sum(signals.pv7.values()) / max(len(signals.pv7), 1)
    valence = 0.3 * prev.valence + 0.4 * tone_valence + 0.3 * (pv7_avg - 0.5) * 2
    valence = max(-1.0, min(1.0, valence))

    urgency_map = {"low": -0.3, "medium": 0.0, "high": 0.5}
    arousal = 0.4 * prev.arousal + 0.6 * urgency_map.get(signals.urgency, 0.0)
    arousal = max(-1.0, min(1.0, arousal))

    risk_map = {"low": 0.3, "medium": 0.0, "high": -0.3, "critical": -0.6}
    dominance = 0.4 * prev.dominance + 0.6 * risk_map.get(signals.risk, 0.0)
    dominance = max(-1.0, min(1.0, dominance))

    fatigue = min(1.0, prev.fatigue + 0.05)
    primary = compute_primary_emotion(valence, arousal, fatigue)

    return EmotionalState(
        valence=round(valence, 4),
        arousal=round(arousal, 4),
        dominance=round(dominance, 4),
        primary_emotion=primary,
        fatigue=round(fatigue, 4),
        pv7_baseline=dict(signals.pv7),
        run_count=prev.run_count + 1,
        last_active_at=new_utc(),
    )


def fatigue_decay(fatigue: float, rest_seconds: float, decay_rate: float = 0.01) -> float:
    amount = decay_rate * (rest_seconds / 60.0)
    return max(0.0, fatigue - amount)


def cap(val: float) -> float:
    return max(-1.0, min(1.0, val))


class HypothalamusStateStore:
    """Persistencia del estado emocional del Hipotálamo en SQLite."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.schema_path = Path(__file__).resolve().parent / "schemas.sql"
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
            self._run_migration(conn)

    def _run_migration(self, conn: sqlite3.Connection) -> None:
        """Ejecuta migración 006 de forma segura (ignora columnas ya existentes)."""
        migration_path = Path(__file__).resolve().parent / "migrations" / "006_hypothalamus_pv14.sql"
        if migration_path.exists():
            try:
                conn.executescript(migration_path.read_text(encoding="utf-8"))
            except sqlite3.OperationalError:
                pass  # Columnas ya existen

    def save(self, run_id: str, signals: SignalPacket, previous: EmotionalState | None = None,
             cognitive_snapshot: dict[str, Any] | None = None) -> int:
        if previous is None:
            previous = self.load_latest()
        mood = mood_from_signals(signals, previous)
        now = new_utc()
        # Merge hardware/cognitive data from previous state or snapshot
        if cognitive_snapshot:
            mood.cpu_load = cognitive_snapshot.get("cpu_load", 0.0)
            mood.ram_usage = cognitive_snapshot.get("ram_usage", 0.0)
            mood.gpu_utilization = cognitive_snapshot.get("gpu_utilization", 0.0)
            mood.gpu_memory_used = cognitive_snapshot.get("gpu_memory_used", 0.0)
            mood.gpu_temperature = cognitive_snapshot.get("gpu_temperature", 0)
            mood.cognitive_load = cognitive_snapshot.get("cognitive_load", 0.0)
            mood.curiosity = cognitive_snapshot.get("curiosity", 0.0)
            mood.uncertainty = cognitive_snapshot.get("uncertainty", 0.0)
            mood.cognitive_snapshot = cognitive_snapshot
        elif previous:
            mood.cpu_load = previous.cpu_load
            mood.ram_usage = previous.ram_usage
            mood.gpu_utilization = previous.gpu_utilization
            mood.gpu_memory_used = previous.gpu_memory_used
            mood.gpu_temperature = previous.gpu_temperature
            mood.cognitive_load = previous.cognitive_load
            mood.curiosity = previous.curiosity
            mood.uncertainty = previous.uncertainty
            mood.cognitive_snapshot = previous.cognitive_snapshot
        with self._connect() as conn:
            try:
                cursor = conn.execute(
                    """INSERT INTO hypothalamus_state
                    (run_id, mood_valence, mood_arousal, mood_dominance, primary_emotion,
                     fatigue, pv7_baseline, run_count, last_active_at, created_at,
                     cpu_load, ram_usage, gpu_utilization, gpu_memory_used, gpu_temperature,
                     cognitive_load, curiosity, uncertainty, tensions_json, cognitive_snapshot_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        mood.valence, mood.arousal, mood.dominance,
                        mood.primary_emotion, mood.fatigue,
                        json.dumps(mood.pv7_baseline, ensure_ascii=False),
                        mood.run_count, mood.last_active_at, now,
                        mood.cpu_load, mood.ram_usage, mood.gpu_utilization,
                        mood.gpu_memory_used, mood.gpu_temperature,
                        mood.cognitive_load, mood.curiosity, mood.uncertainty,
                        json.dumps(mood.tensions, ensure_ascii=False),
                        json.dumps(mood.cognitive_snapshot, ensure_ascii=False),
                    ),
                )
                return int(cursor.lastrowid)
            except sqlite3.IntegrityError:
                # FK constraint: run_id no existe en tabla runs. Insertar registro mínimo.
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO runs (run_id, user_input, created_at) VALUES (?, '', ?)",
                        (run_id, now),
                    )
                    cursor = conn.execute(
                        """INSERT INTO hypothalamus_state
                        (run_id, mood_valence, mood_arousal, mood_dominance, primary_emotion,
                         fatigue, pv7_baseline, run_count, last_active_at, created_at,
                         cpu_load, ram_usage, gpu_utilization, gpu_memory_used, gpu_temperature,
                         cognitive_load, curiosity, uncertainty, tensions_json, cognitive_snapshot_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            run_id,
                            mood.valence, mood.arousal, mood.dominance,
                            mood.primary_emotion, mood.fatigue,
                            json.dumps(mood.pv7_baseline, ensure_ascii=False),
                            mood.run_count, mood.last_active_at, now,
                            mood.cpu_load, mood.ram_usage, mood.gpu_utilization,
                            mood.gpu_memory_used, mood.gpu_temperature,
                            mood.cognitive_load, mood.curiosity, mood.uncertainty,
                            json.dumps(mood.tensions, ensure_ascii=False),
                            json.dumps(mood.cognitive_snapshot, ensure_ascii=False),
                        ),
                    )
                    return int(cursor.lastrowid)
                except Exception:
                    return -1

    def save_raw(self, run_id: str, state: EmotionalState) -> int:
        now = new_utc()
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO hypothalamus_state
                (run_id, mood_valence, mood_arousal, mood_dominance, primary_emotion,
                 fatigue, pv7_baseline, run_count, last_active_at, created_at,
                 cpu_load, ram_usage, gpu_utilization, gpu_memory_used, gpu_temperature,
                 cognitive_load, curiosity, uncertainty, tensions_json, cognitive_snapshot_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, state.valence, state.arousal, state.dominance,
                    state.primary_emotion, state.fatigue,
                    json.dumps(state.pv7_baseline, ensure_ascii=False),
                    state.run_count, state.last_active_at, now,
                    state.cpu_load, state.ram_usage, state.gpu_utilization,
                    state.gpu_memory_used, state.gpu_temperature,
                    state.cognitive_load, state.curiosity, state.uncertainty,
                    json.dumps(state.tensions, ensure_ascii=False),
                    json.dumps(state.cognitive_snapshot, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def load_latest(self) -> EmotionalState | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM hypothalamus_state ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return self._row_to_state(row)

    def load_all(self, limit: int = 50) -> list[EmotionalState]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM hypothalamus_state ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_state(r) for r in rows]

    def update_fatigue(self, new_fatigue: float) -> bool:
        latest = self.load_latest()
        if latest is None:
            return False
        clamped = cap(new_fatigue)
        with self._connect() as conn:
            conn.execute(
                """UPDATE hypothalamus_state
                SET fatigue = ?
                WHERE id = (SELECT MAX(id) FROM hypothalamus_state)""",
                (clamped,),
            )
        return True

    def update_fatigue_with_timestamp(self, run_id: str, fatigue: float, timestamp: str) -> int:
        clamped = cap(fatigue)
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO hypothalamus_state
                (run_id, mood_valence, mood_arousal, mood_dominance, primary_emotion,
                 fatigue, pv7_baseline, run_count, last_active_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, 0.0, 0.0, 0.0, "resting", clamped,
                    "{}", 0, timestamp, new_utc(),
                ),
            )
            return int(cursor.lastrowid)

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM hypothalamus_state").fetchone()
            return row["c"] if row else 0

    def reinforce(self, run_id: str, reward: float, hypothalamus_quality: float = 0.0, central_quality: float = 0.0, coherence_score: float = 0.0) -> EmotionalState | None:
        latest = self.load_latest()
        if latest is None:
            return None

        before_valence = latest.valence
        before_fatigue = latest.fatigue

        latest.valence = cap(latest.valence + reward * 0.2)
        latest.dominance = cap(latest.dominance + reward * 0.15)
        latest.fatigue = cap(max(0.0, latest.fatigue - reward * 0.1))
        latest.primary_emotion = compute_primary_emotion(latest.valence, latest.arousal, latest.fatigue)
        latest.last_active_at = new_utc()

        self.save_raw(run_id, latest)

        self._store_reinforcement(run_id, reward, hypothalamus_quality, central_quality, coherence_score, before_valence, latest.valence, before_fatigue, latest.fatigue)

        return latest

    def _store_reinforcement(self, run_id: str, reward: float, hyp_q: float, cen_q: float, coh: float, val_before: float, val_after: float, fat_before: float, fat_after: float) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO reinforcement_log
                (run_id, reward, hypothalamus_quality, central_quality, coherence_score,
                 mood_valence_before, mood_valence_after, fatigue_before, fatigue_after)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, reward, hyp_q, cen_q, coh, val_before, val_after, fat_before, fat_after),
            )
            return int(cursor.lastrowid)

    def reinforcement_history(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM reinforcement_log ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def avg_reward(self, limit: int = 50) -> float:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT AVG(reward) AS avg_reward FROM (SELECT reward FROM reinforcement_log ORDER BY id DESC LIMIT ?)""",
                (limit,),
            ).fetchone()
            return round(float(row["avg_reward"]), 6) if row and row["avg_reward"] is not None else 0.0

    def doctor(self) -> dict[str, Any]:
        latest = self.load_latest()
        reward_count = 0
        avg_reward = 0.0
        try:
            reward_count = len(self.reinforcement_history(1000))
            avg_reward = self.avg_reward(50)
        except Exception as exc:
            from triade.core.error_bus import record_internal_error
            record_internal_error(
                "hypothalamus_store.doctor.reinforcement",
                exc,
                payload={"module": __name__, "function": "doctor", "operation": "load_reinforcement_summary"},
                db_path=self.db_path,
            )
        return {
            "status": "ok",
            "count": self.count(),
            "latest": latest.to_dict() if latest else None,
            "reinforcement": {
                "events": reward_count,
                "avg_reward_last_50": round(avg_reward, 4),
            },
        }

    def learn_pattern(self, text: str, intent: str, tone: str, risk: str, urgency: str, confidence: float = 0.8) -> int:
        """Aprende un patrón de análisis para uso futuro."""
        now = new_utc()
        text_hash = self._hash_text(text)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, confidence, hit_count FROM hypothalamus_patterns WHERE text_hash = ?",
                (text_hash,),
            ).fetchone()
            if existing:
                new_conf = min(1.0, float(existing["confidence"]) + 0.05)
                new_hits = int(existing["hit_count"]) + 1
                conn.execute(
                    "UPDATE hypothalamus_patterns SET confidence = ?, hit_count = ?, last_used_at = ? WHERE id = ?",
                    (new_conf, new_hits, now, existing["id"]),
                )
                return int(existing["id"])
            cursor = conn.execute(
                """INSERT INTO hypothalamus_patterns
                (text_hash, text_preview, intent, tone, risk, urgency, confidence, hit_count, created_at, last_used_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (text_hash, text[:200], intent, tone, risk, urgency, confidence, 1, now, now),
            )
            return int(cursor.lastrowid)

    def recall_pattern(self, text: str) -> dict[str, Any] | None:
        """Recupera un patrón aprendido para el texto dado."""
        text_hash = self._hash_text(text)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM hypothalamus_patterns WHERE text_hash = ? AND confidence >= 0.5",
                (text_hash,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def top_patterns(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM hypothalamus_patterns ORDER BY confidence DESC, hit_count DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def decay_patterns(self, decay_rate: float = 0.01) -> int:
        """Decae confianza de patrones no usados recientemente."""
        with self._connect() as conn:
            cursor = conn.execute(
                """UPDATE hypothalamus_patterns
                SET confidence = MAX(0.0, confidence - ?)
                WHERE last_used_at < datetime('now', '-7 days')""",
                (decay_rate,),
            )
            return cursor.rowcount

    @staticmethod
    def _hash_text(text: str) -> str:
        import hashlib
        normalized = text.lower().strip()[:100]
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _row_to_state(row: sqlite3.Row) -> EmotionalState:
        def r(key: str, default: object = "") -> object:
            try:
                return row[key]
            except (KeyError, IndexError):
                return default

        pv7_raw = r("pv7_baseline", "{}")
        try:
            pv7 = json.loads(str(pv7_raw)) if isinstance(pv7_raw, str) else {}
        except (json.JSONDecodeError, TypeError):
            pv7 = {}

        tensions_raw = r("tensions_json", "{}")
        try:
            tensions = json.loads(str(tensions_raw)) if isinstance(tensions_raw, str) else {}
        except (json.JSONDecodeError, TypeError):
            tensions = {}

        cog_raw = r("cognitive_snapshot_json", "{}")
        try:
            cognitive_snapshot = json.loads(str(cog_raw)) if isinstance(cog_raw, str) else {}
        except (json.JSONDecodeError, TypeError):
            cognitive_snapshot = {}

        return EmotionalState(
            valence=float(r("mood_valence", 0.0)),
            arousal=float(r("mood_arousal", 0.0)),
            dominance=float(r("mood_dominance", 0.0)),
            primary_emotion=str(r("primary_emotion", "neutral")),
            fatigue=float(r("fatigue", 0.0)),
            pv7_baseline=pv7,
            run_count=int(r("run_count", 0)),
            last_active_at=str(r("last_active_at") or r("created_at", "")),
            cpu_load=float(r("cpu_load", 0.0)),
            ram_usage=float(r("ram_usage", 0.0)),
            gpu_utilization=float(r("gpu_utilization", 0.0)),
            gpu_memory_used=float(r("gpu_memory_used", 0.0)),
            gpu_temperature=int(r("gpu_temperature", 0)),
            cognitive_load=float(r("cognitive_load", 0.0)),
            curiosity=float(r("curiosity", 0.0)),
            uncertainty=float(r("uncertainty", 0.0)),
            tensions=tensions,
            cognitive_snapshot=cognitive_snapshot,
        )

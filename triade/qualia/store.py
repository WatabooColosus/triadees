"""Persistencia SQLite segura para QualiaBus."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .contracts import CentralKnowledgePacket, NeuronExperience, QualiaSignal, QualiaState, StorageMemoryPacket

QUALIA_SCHEMA = """
CREATE TABLE IF NOT EXISTS qualia_experiences (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    neuron_id TEXT,
    neuron_type TEXT,
    mission TEXT,
    source TEXT,
    source_type TEXT,
    observation TEXT,
    extracted_pattern TEXT,
    proposed_learning TEXT,
    confidence REAL DEFAULT 0.0,
    risk TEXT DEFAULT 'low',
    usefulness REAL DEFAULT 0.0,
    emotional_signal_json TEXT,
    evidence_refs_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS qualia_signals (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    experience_id TEXT,
    signal_type TEXT,
    intensity REAL DEFAULT 0.0,
    valence REAL DEFAULT 0.0,
    urgency REAL DEFAULT 0.0,
    curiosity REAL DEFAULT 0.0,
    risk REAL DEFAULT 0.0,
    confidence REAL DEFAULT 0.0,
    tone_hint TEXT,
    reason TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS qualia_central_packets (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    experience_id TEXT,
    claim TEXT,
    hypothesis TEXT,
    decision_hint TEXT,
    validation_need TEXT,
    related_goals_json TEXT,
    confidence REAL DEFAULT 0.0,
    evidence_refs_json TEXT,
    status TEXT DEFAULT 'hypothesis',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS qualia_storage_packets (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    experience_id TEXT,
    memory_type TEXT,
    category TEXT,
    subcategory TEXT,
    content TEXT,
    source TEXT,
    content_hash TEXT,
    confidence REAL DEFAULT 0.0,
    verification_status TEXT DEFAULT 'unverified',
    promotion_status TEXT DEFAULT 'candidate',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS qualia_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    curiosity REAL DEFAULT 0.0,
    confidence REAL DEFAULT 0.0,
    risk REAL DEFAULT 0.0,
    urgency REAL DEFAULT 0.0,
    coherence REAL DEFAULT 0.0,
    novelty REAL DEFAULT 0.0,
    usefulness REAL DEFAULT 0.0,
    saturation REAL DEFAULT 0.0,
    dominant_signal TEXT DEFAULT 'none',
    recommended_action TEXT DEFAULT 'observe',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_qualia_experiences_run_id ON qualia_experiences(run_id);
CREATE INDEX IF NOT EXISTS idx_qualia_experiences_source_type ON qualia_experiences(source_type);
CREATE INDEX IF NOT EXISTS idx_qualia_signals_run_id ON qualia_signals(run_id);
CREATE INDEX IF NOT EXISTS idx_qualia_signals_experience_id ON qualia_signals(experience_id);
CREATE INDEX IF NOT EXISTS idx_qualia_central_packets_run_id ON qualia_central_packets(run_id);
CREATE INDEX IF NOT EXISTS idx_qualia_storage_packets_run_id ON qualia_storage_packets(run_id);
CREATE INDEX IF NOT EXISTS idx_qualia_states_run_id ON qualia_states(run_id);
"""


class QualiaStore:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db", schema_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path)
        repo_root = Path(__file__).resolve().parents[2]
        self.schema_path = Path(schema_path) if schema_path is not None else repo_root / "triade/memory/schemas.sql"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            if self.schema_path.exists():
                conn.executescript(self.schema_path.read_text(encoding="utf-8"))
            conn.executescript(QUALIA_SCHEMA)

    def ensure_schema(self) -> None:
        self._init_db()

    def store_experience(self, exp: NeuronExperience) -> str:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO qualia_experiences
                (id, run_id, neuron_id, neuron_type, mission, source, source_type, observation,
                 extracted_pattern, proposed_learning, confidence, risk, usefulness, emotional_signal_json,
                 evidence_refs_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (exp.id, exp.run_id, str(exp.neuron_id) if exp.neuron_id is not None else None, exp.neuron_type,
                 exp.mission, exp.source, exp.source_type, exp.observation, exp.extracted_pattern,
                 exp.proposed_learning, exp.confidence, exp.risk, exp.usefulness,
                 json.dumps(exp.emotional_signal, ensure_ascii=False), json.dumps(exp.evidence_refs, ensure_ascii=False), exp.created_at),
            )
        return exp.id

    def store_signal(self, signal: QualiaSignal) -> str:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO qualia_signals
                (id, run_id, experience_id, signal_type, intensity, valence, urgency, curiosity, risk,
                 confidence, tone_hint, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (signal.id, signal.run_id, signal.experience_id, signal.signal_type, signal.intensity,
                 signal.valence, signal.urgency, signal.curiosity, signal.risk, signal.confidence,
                 signal.tone_hint, signal.reason, signal.created_at),
            )
        return signal.id

    def store_central_packet(self, packet: CentralKnowledgePacket) -> str:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO qualia_central_packets
                (id, run_id, experience_id, claim, hypothesis, decision_hint, validation_need,
                 related_goals_json, confidence, evidence_refs_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (packet.id, packet.run_id, packet.experience_id, packet.claim, packet.hypothesis,
                 packet.decision_hint, packet.validation_need, json.dumps(packet.related_goals, ensure_ascii=False),
                 packet.confidence, json.dumps(packet.evidence_refs, ensure_ascii=False), packet.status, packet.created_at),
            )
        return packet.id

    def store_storage_packet(self, packet: StorageMemoryPacket) -> str:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO qualia_storage_packets
                (id, run_id, experience_id, memory_type, category, subcategory, content, source,
                 content_hash, confidence, verification_status, promotion_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (packet.id, packet.run_id, packet.experience_id, packet.memory_type, packet.category,
                 packet.subcategory, packet.content, packet.source, packet.content_hash, packet.confidence,
                 packet.verification_status, packet.promotion_status, packet.created_at),
            )
        return packet.id

    def store_state(self, state: QualiaState) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO qualia_states
                (run_id, curiosity, confidence, risk, urgency, coherence, novelty, usefulness,
                 saturation, dominant_signal, recommended_action, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (state.run_id, state.curiosity, state.confidence, state.risk, state.urgency,
                 state.coherence, state.novelty, state.usefulness, state.saturation,
                 state.dominant_signal, state.recommended_action, state.updated_at),
            )
            return int(cur.lastrowid)

    def persist_bundle(self, bundle: Any) -> dict[str, Any]:
        self.store_experience(bundle.experience)
        self.store_signal(bundle.signal)
        self.store_central_packet(bundle.central_packet)
        self.store_storage_packet(bundle.storage_packet)
        return {
            "experience_id": bundle.experience.id,
            "signal_id": bundle.signal.id,
            "central_packet_id": bundle.central_packet.id,
            "storage_packet_id": bundle.storage_packet.id,
        }

    def list_experiences(self, run_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return self._list("qualia_experiences", run_id, limit, json_fields={"emotional_signal_json": "emotional_signal", "evidence_refs_json": "evidence_refs"})

    def list_signals(self, run_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return self._list("qualia_signals", run_id, limit)

    def list_central_packets(self, run_id: str | None = None, limit: int = 50, statuses: set[str] | None = None) -> list[dict[str, Any]]:
        rows = self._list("qualia_central_packets", run_id, limit, json_fields={"related_goals_json": "related_goals", "evidence_refs_json": "evidence_refs"})
        if statuses:
            rows = [row for row in rows if str(row.get("status")) in statuses]
        return rows

    def list_storage_packets(self, run_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return self._list("qualia_storage_packets", run_id, limit)

    def list_states(self, run_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        return self._list("qualia_states", run_id, limit)

    def latest_state(self, run_id: str | None = None) -> dict[str, Any] | None:
        rows = self.list_states(run_id=run_id, limit=1)
        return rows[0] if rows else None

    def counts(self, run_id: str | None = None) -> dict[str, int]:
        tables = ["qualia_experiences", "qualia_signals", "qualia_central_packets", "qualia_storage_packets", "qualia_states"]
        result: dict[str, int] = {}
        with self._connect() as conn:
            for table in tables:
                if run_id:
                    row = conn.execute(f"SELECT COUNT(*) AS c FROM {table} WHERE run_id = ?", (run_id,)).fetchone()
                else:
                    row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
                result[table] = int(row["c"])
        return result

    def doctor(self) -> dict[str, Any]:
        required = {"qualia_experiences", "qualia_signals", "qualia_central_packets", "qualia_storage_packets", "qualia_states"}
        try:
            with self._connect() as conn:
                tables = {str(r["name"]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            missing = sorted(required - tables)
            return {"status": "ok" if not missing else "missing_tables", "missing_tables": missing, "counts": self.counts() if not missing else {}}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def _list(self, table: str, run_id: str | None, limit: int, json_fields: dict[str, str] | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if run_id:
                rows = conn.execute(f"SELECT * FROM {table} WHERE run_id = ? ORDER BY rowid DESC LIMIT ?", (run_id, limit)).fetchall()
            else:
                rows = conn.execute(f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
        decoded = [dict(row) for row in rows]
        for row in decoded:
            for src, dest in (json_fields or {}).items():
                try:
                    row[dest] = json.loads(row.pop(src, "") or "[]")
                except (TypeError, json.JSONDecodeError):
                    row[dest] = []
        return decoded

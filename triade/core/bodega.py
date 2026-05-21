"""Bodega de Almacenamiento · SQLite MVP real.

Inicializa SQLite, carga el esquema base, recupera identidad, consulta memoria simple
y guarda episodios, señales, cristal, safety, reportes y eventos de modelos por run.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .contracts import (
    CrystalPacket,
    InputPacket,
    MemoryPacket,
    OutputPacket,
    SafetyPacket,
    SignalPacket,
    VerificationReport,
)


class Bodega:
    """Memoria funcional con persistencia SQLite."""

    CRYSTAL_V2_COLUMNS = {
        "pv7_score": "REAL DEFAULT 0.5",
        "stability": "REAL DEFAULT 0.5",
        "intensity": "REAL DEFAULT 0.5",
        "q_crystal": "REAL DEFAULT 0.0",
        "ethics_vector": "TEXT",
        "regulation_notes": "TEXT",
    }

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.schema_path = Path("triade/memory/schemas.sql")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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
            self._migrate_crystal_v2(conn)

    def _migrate_crystal_v2(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(crystal_states)").fetchall()}
        for column, definition in self.CRYSTAL_V2_COLUMNS.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE crystal_states ADD COLUMN {column} {definition}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crystal_states_run_id ON crystal_states(run_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crystal_states_q_crystal ON crystal_states(q_crystal)")

    def recall(self, packet: InputPacket) -> MemoryPacket:
        """Recupera identidad y memoria simple relacionada con la entrada."""
        identity = self._fetch_identity()
        semantic = self._search_semantic(packet.user_input)
        episodic = self._search_episodic(packet.user_input)

        confidence = 0.4
        if identity:
            confidence += 0.2
        if semantic or episodic:
            confidence += 0.3

        return MemoryPacket(
            run_id=packet.run_id,
            identity_matches=identity,
            semantic_matches=semantic,
            episodic_matches=episodic,
            confidence=min(confidence, 1.0),
        )

    def create_run(self, packet: InputPacket) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO runs (run_id, source, user_input, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (packet.run_id, packet.source, packet.user_input, "created", packet.timestamp),
            )

    def update_run_models(self, run_id: str, model_hypothalamus: str, model_central: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE runs
                SET model_hypothalamus = ?, model_central = ?
                WHERE run_id = ?
                """,
                (model_hypothalamus, model_central, run_id),
            )

    def store_model_event(
        self,
        run_id: str,
        role: str,
        provider: str,
        model_name: str,
        ok: bool,
        error: str | None = None,
        quality_score: float = 0.0,
        latency_ms: int | None = None,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO model_events
                (run_id, role, provider, model_name, ok, error, quality_score, latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, role, provider, model_name, 1 if ok else 0, error, quality_score, latency_ms),
            )
            return int(cursor.lastrowid)

    def store_signal(self, signals: SignalPacket) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO signal_states (run_id, intent, tone, urgency, risk, pv7, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signals.run_id,
                    signals.intent,
                    signals.tone,
                    signals.urgency,
                    signals.risk,
                    json.dumps(signals.pv7, ensure_ascii=False),
                    json.dumps(signals.notes, ensure_ascii=False),
                    signals.timestamp,
                ),
            )
            return int(cursor.lastrowid)

    def store_crystal(self, crystal: CrystalPacket) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO crystal_states
                (run_id, ethics, depth, creativity, relation, pv7_score, stability, intensity,
                 q_crystal, ethics_vector, regulation_notes, decision_notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    crystal.run_id,
                    crystal.ethics,
                    crystal.depth,
                    crystal.creativity,
                    crystal.relation,
                    crystal.pv7_score,
                    crystal.stability,
                    crystal.intensity,
                    crystal.q_crystal,
                    json.dumps(crystal.ethics_vector, ensure_ascii=False),
                    json.dumps(crystal.regulation_notes, ensure_ascii=False),
                    json.dumps(crystal.decision_notes, ensure_ascii=False),
                    crystal.timestamp,
                ),
            )
            return int(cursor.lastrowid)

    def store_safety(self, safety: SafetyPacket) -> int:
        """Guarda safety como evento semántico de auditoría mínima."""
        pattern_id = f"safety-{safety.run_id}"
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR REPLACE INTO knowledge_patterns
                (pattern_id, name, description, domain, pattern_body, source_ref, confidence, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pattern_id,
                    "SafetyPacket",
                    safety.reason,
                    "safety",
                    json.dumps(safety.to_dict(), ensure_ascii=False),
                    safety.run_id,
                    0.8,
                    safety.status,
                    safety.timestamp,
                    safety.timestamp,
                ),
            )
            return int(cursor.lastrowid)

    def store_verification_report(self, report: VerificationReport) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO verification_reports
                (run_id, status, coherence_score, memory_score, safety_score, usefulness_score,
                 traceability_score, errors, warnings, recommendations, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.run_id,
                    report.status,
                    report.coherence_score,
                    report.memory_score,
                    report.safety_score,
                    report.usefulness_score,
                    report.traceability_score,
                    json.dumps(report.errors, ensure_ascii=False),
                    json.dumps(report.warnings, ensure_ascii=False),
                    json.dumps(report.recommendations, ensure_ascii=False),
                    report.timestamp,
                ),
            )
            return int(cursor.lastrowid)

    def store_episode(self, input_packet: InputPacket, output: OutputPacket) -> dict[str, Any]:
        """Guarda un episodio básico del run."""
        title = self._make_title(input_packet.user_input)
        content = f"Usuario: {input_packet.user_input}\nRespuesta: {output.response}"
        summary = output.response[:280]
        tags = "triade,mvp,run"

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE runs
                SET status = ?, closed_at = ?
                WHERE run_id = ?
                """,
                (output.status, output.timestamp, input_packet.run_id),
            )
            cursor = conn.execute(
                """
                INSERT INTO episodic_memory (run_id, title, content, summary, tags, importance, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (input_packet.run_id, title, content, summary, tags, 0.5, 0.75),
            )
            episode_id = cursor.lastrowid

        return {
            "run_id": output.run_id,
            "stored": True,
            "episode_id": episode_id,
            "db_path": str(self.db_path),
        }

    def diff_from_output(self, output: OutputPacket) -> dict[str, object]:
        return {
            "run_id": output.run_id,
            "stored": False,
            "reason": "Usar store_episode(input_packet, output) para persistencia real.",
        }

    def list_recent_episodes(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, run_id, title, summary, tags, confidence, created_at
                FROM episodic_memory
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def doctor(self, runs_dir: str | Path = "runs") -> dict[str, Any]:
        """Diagnóstico local de instalación, memoria y runs."""
        runs_path = Path(runs_dir)
        with self._connect() as conn:
            tables = [row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
            run_count = conn.execute("SELECT COUNT(*) AS c FROM runs").fetchone()["c"]
            episode_count = conn.execute("SELECT COUNT(*) AS c FROM episodic_memory").fetchone()["c"]
            signal_count = conn.execute("SELECT COUNT(*) AS c FROM signal_states").fetchone()["c"]
            crystal_count = conn.execute("SELECT COUNT(*) AS c FROM crystal_states").fetchone()["c"]
            verification_count = conn.execute("SELECT COUNT(*) AS c FROM verification_reports").fetchone()["c"]
            safety_count = conn.execute("SELECT COUNT(*) AS c FROM knowledge_patterns WHERE domain = 'safety'").fetchone()["c"]
            model_event_count = conn.execute("SELECT COUNT(*) AS c FROM model_events").fetchone()["c"]
            model_rows = conn.execute(
                """
                SELECT model_hypothalamus, model_central, COUNT(*) AS c
                FROM runs
                WHERE model_hypothalamus IS NOT NULL OR model_central IS NOT NULL
                GROUP BY model_hypothalamus, model_central
                ORDER BY c DESC
                """
            ).fetchall()
            model_event_rows = conn.execute(
                """
                SELECT role, provider, model_name, ok, COUNT(*) AS c, AVG(quality_score) AS avg_quality
                FROM model_events
                GROUP BY role, provider, model_name, ok
                ORDER BY c DESC
                """
            ).fetchall()
            crystal_quality = conn.execute(
                """
                SELECT AVG(q_crystal) AS avg_q_crystal,
                       AVG(stability) AS avg_stability,
                       AVG(intensity) AS avg_intensity,
                       AVG(pv7_score) AS avg_pv7_score
                FROM crystal_states
                """
            ).fetchone()

        return {
            "status": "ok",
            "db_path": str(self.db_path),
            "db_exists": self.db_path.exists(),
            "schema_path": str(self.schema_path),
            "schema_exists": self.schema_path.exists(),
            "runs_dir": str(runs_path),
            "runs_dir_exists": runs_path.exists(),
            "tables": tables,
            "counts": {
                "runs": run_count,
                "episodes": episode_count,
                "signals": signal_count,
                "crystals": crystal_count,
                "safety_events": safety_count,
                "verification_reports": verification_count,
                "model_events": model_event_count,
            },
            "crystal_quality": dict(crystal_quality) if crystal_quality else {},
            "model_usage": [dict(row) for row in model_rows],
            "model_events": [dict(row) for row in model_event_rows],
        }

    def _fetch_identity(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT key, value, category, confidence
                FROM identity_core
                ORDER BY id ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def _search_semantic(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        terms = self._terms(query)
        if not terms:
            return []
        like_clauses = " OR ".join(["value LIKE ? OR key LIKE ? OR domain LIKE ?" for _ in terms])
        params: list[str] = []
        for term in terms:
            pattern = f"%{term}%"
            params.extend([pattern, pattern, pattern])
        sql = f"""
            SELECT key, value, domain, source_ref, confidence, status
            FROM semantic_memory
            WHERE {like_clauses}
            ORDER BY confidence DESC
            LIMIT ?
        """
        params.append(str(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def _search_episodic(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        terms = self._terms(query)
        if not terms:
            return []
        like_clauses = " OR ".join(["content LIKE ? OR summary LIKE ? OR title LIKE ? OR tags LIKE ?" for _ in terms])
        params: list[str] = []
        for term in terms:
            pattern = f"%{term}%"
            params.extend([pattern, pattern, pattern, pattern])
        sql = f"""
            SELECT id, run_id, title, summary, tags, confidence, created_at
            FROM episodic_memory
            WHERE {like_clauses}
            ORDER BY id DESC
            LIMIT ?
        """
        params.append(str(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _terms(query: str) -> list[str]:
        stop = {"el", "la", "los", "las", "un", "una", "de", "del", "y", "o", "a", "en", "que", "por", "para"}
        words = [w.strip(".,:;!?¡¿()[]{}\"'").lower() for w in query.split()]
        return [w for w in words if len(w) >= 4 and w not in stop][:6]

    @staticmethod
    def _make_title(text: str) -> str:
        clean = " ".join(text.strip().split())
        return clean[:80] if clean else "Run sin título"

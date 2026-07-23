"""Bodega de Almacenamiento · SQLite MVP real.

Inicializa SQLite, recupera identidad y memoria, y persiste evidencia auditable
por run. Crystal v2 conserva historial temporal contextualizado. Desde 1.9D,
Bodega puede incorporar recuerdos vectoriales de manera explícita y auditable.
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
        "previous_q_crystal": "REAL",
        "previous_stability": "REAL",
        "q_delta": "REAL DEFAULT 0.0",
        "stability_delta": "REAL DEFAULT 0.0",
        "temporal_status": "TEXT DEFAULT 'baseline'",
        "temporal_alerts": "TEXT",
        "history_window": "INTEGER DEFAULT 0",
        "context_scope": "TEXT DEFAULT 'source_intent'",
        "context_key": "TEXT",
        "comparison_basis": "TEXT",
        "source": "TEXT",
        "intent": "TEXT",
        "session_id": "TEXT",
        "project_id": "TEXT",
        "active_neuron": "TEXT",
    }

    def __init__(self, db_path: str | Path = "triade/memory/triade.db", semantic_search_engine: Any | None = None) -> None:
        self.db_path = Path(db_path)
        self.schema_path = Path(__file__).resolve().parents[2] / "triade/memory/schemas.sql"
        self.semantic_search_engine = semantic_search_engine
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crystal_states_temporal_status ON crystal_states(temporal_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_crystal_states_context_key ON crystal_states(context_key)")

    def recall(
        self,
        packet: InputPacket,
        semantic_recall_enabled: bool = False,
        semantic_model: str | None = None,
        semantic_limit: int = 3,
        semantic_min_similarity: float = 0.55,
        semantic_domain: str | None = None,
    ) -> MemoryPacket:
        identity = self._fetch_identity()
        keyword_semantic = [
            {**match, "retrieval_type": "legacy_keyword"}
            for match in self._search_semantic(packet.user_input)
        ]
        episodic = self._search_episodic(packet.user_input)
        vector_semantic: list[dict[str, Any]] = []
        semantic_recall: dict[str, Any] = {
            "enabled": semantic_recall_enabled,
            "mode": "vector_similarity" if semantic_recall_enabled else "disabled",
            "model": semantic_model,
            "limit": semantic_limit,
            "min_similarity": semantic_min_similarity,
            "domain": semantic_domain,
            "status": "disabled" if not semantic_recall_enabled else "pending",
            "matches_count": 0,
        }

        if semantic_recall_enabled:
            if self.semantic_search_engine is None:
                semantic_recall.update({
                    "status": "unavailable",
                    "error": "SemanticSearchEngine no fue configurado para este run.",
                })
            else:
                search_result = self.semantic_search_engine.search(
                    query=packet.user_input,
                    model=semantic_model,
                    limit=semantic_limit,
                    min_similarity=semantic_min_similarity,
                    domain=semantic_domain,
                )
                semantic_recall.update({
                    "status": search_result.get("status", "failed"),
                    "model": search_result.get("model", semantic_model),
                    "query_dimensions": search_result.get("query_dimensions"),
                    "candidate_embeddings": search_result.get("candidate_embeddings", 0),
                    "matching_candidates": search_result.get("matching_candidates", 0),
                    "skipped_model": search_result.get("skipped_model", 0),
                    "skipped_dimensions": search_result.get("skipped_dimensions", 0),
                    "error": search_result.get("error"),
                })
                if search_result.get("status") == "ok":
                    vector_semantic = [
                        {**match, "retrieval_type": "vector_similarity"}
                        for match in search_result.get("results", [])
                    ]
                    semantic_recall["matches_count"] = len(vector_semantic)

        semantic = vector_semantic + keyword_semantic
        confidence = 0.4
        if identity:
            confidence += 0.2
        if episodic or keyword_semantic:
            confidence += 0.2
        if vector_semantic:
            strongest = max(float(match.get("similarity", 0.0)) for match in vector_semantic)
            confidence += 0.2 if strongest >= semantic_min_similarity else 0.1
            semantic_recall["strongest_similarity"] = round(strongest, 6)
        return MemoryPacket(
            run_id=packet.run_id,
            identity_matches=identity,
            semantic_matches=semantic,
            episodic_matches=episodic,
            semantic_recall=semantic_recall,
            confidence=min(confidence, 1.0),
        )

    def create_run(self, packet: InputPacket) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO runs (run_id, source, user_input, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (packet.run_id, packet.source, packet.user_input, "created", packet.timestamp),
            )

    def update_run_models(self, run_id: str, model_hypothalamus: str, model_central: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE runs SET model_hypothalamus = ?, model_central = ? WHERE run_id = ?",
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
            # Diagnostics and background probes may emit model events outside
            # a full runner cycle. Preserve referential integrity by creating
            # an idempotent synthetic parent when needed.
            conn.execute(
                """
                INSERT OR IGNORE INTO runs (run_id, source, user_input, status)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, "model_event", "Model event diagnostic", "ok"),
            )
            cursor = conn.execute(
                """INSERT INTO model_events
                (run_id, role, provider, model_name, ok, error, quality_score, latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, role, provider, model_name, 1 if ok else 0, error, quality_score, latency_ms),
            )
            return int(cursor.lastrowid)

    def store_signal(self, signals: SignalPacket) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO signal_states (run_id, intent, tone, urgency, risk, pv7, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
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
        basis = crystal.comparison_basis or {}
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO crystal_states
                (run_id, ethics, depth, creativity, relation, pv7_score, stability, intensity,
                 q_crystal, ethics_vector, regulation_notes, previous_q_crystal, previous_stability,
                 q_delta, stability_delta, temporal_status, temporal_alerts, history_window,
                 context_scope, context_key, comparison_basis, source, intent, session_id,
                 project_id, active_neuron, decision_notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    crystal.previous_q_crystal,
                    crystal.previous_stability,
                    crystal.q_delta,
                    crystal.stability_delta,
                    crystal.temporal_status,
                    json.dumps(crystal.temporal_alerts, ensure_ascii=False),
                    crystal.history_window,
                    crystal.context_scope,
                    crystal.context_key,
                    json.dumps(basis, ensure_ascii=False),
                    basis.get("source"),
                    basis.get("intent"),
                    basis.get("session_id"),
                    basis.get("project_id"),
                    basis.get("active_neuron"),
                    json.dumps(crystal.decision_notes, ensure_ascii=False),
                    crystal.timestamp,
                ),
            )
            return int(cursor.lastrowid)

    def list_recent_crystals(self, limit: int = 5, context_key: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if context_key:
                rows = conn.execute(
                    """SELECT run_id, q_crystal, stability, intensity, pv7_score, temporal_status,
                    context_scope, context_key, source, intent, session_id, project_id, active_neuron, created_at
                    FROM crystal_states WHERE context_key = ? ORDER BY id DESC LIMIT ?""",
                    (context_key, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT run_id, q_crystal, stability, intensity, pv7_score, temporal_status,
                    context_scope, context_key, source, intent, session_id, project_id, active_neuron, created_at
                    FROM crystal_states ORDER BY id DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def store_safety(self, safety: SafetyPacket) -> int:
        pattern_id = f"safety-{safety.run_id}"
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT OR REPLACE INTO knowledge_patterns
                (pattern_id, name, description, domain, pattern_body, source_ref, confidence, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                """INSERT INTO verification_reports
                (run_id, status, coherence_score, memory_score, safety_score, usefulness_score,
                 traceability_score, errors, warnings, recommendations, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        title = self._make_title(input_packet.user_input)
        content = f"Usuario: {input_packet.user_input}\nRespuesta: {output.response}"
        summary = output.response[:280]
        tags = "triade,mvp,run"
        with self._connect() as conn:
            conn.execute(
                "UPDATE runs SET status = ?, closed_at = ? WHERE run_id = ?",
                (output.status, output.timestamp, input_packet.run_id),
            )
            cursor = conn.execute(
                """INSERT INTO episodic_memory (run_id, title, content, summary, tags, importance, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (input_packet.run_id, title, content, summary, tags, 0.5, 0.75),
            )
            episode_id = cursor.lastrowid
        return {"run_id": output.run_id, "stored": True, "episode_id": episode_id, "db_path": str(self.db_path)}

    def diff_from_output(self, output: OutputPacket) -> dict[str, object]:
        return {"run_id": output.run_id, "stored": False, "reason": "Usar store_episode(input_packet, output) para persistencia real."}

    def list_recent_episodes(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, run_id, title, summary, tags, confidence, created_at
                FROM episodic_memory ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def doctor(self, runs_dir: str | Path = "runs") -> dict[str, Any]:
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
                """SELECT model_hypothalamus, model_central, COUNT(*) AS c FROM runs
                WHERE model_hypothalamus IS NOT NULL OR model_central IS NOT NULL
                GROUP BY model_hypothalamus, model_central ORDER BY c DESC"""
            ).fetchall()
            model_event_rows = conn.execute(
                """SELECT role, provider, model_name, ok, COUNT(*) AS c, AVG(quality_score) AS avg_quality
                FROM model_events GROUP BY role, provider, model_name, ok ORDER BY c DESC"""
            ).fetchall()
            crystal_quality = conn.execute(
                """SELECT AVG(q_crystal) AS avg_q_crystal, AVG(stability) AS avg_stability,
                AVG(intensity) AS avg_intensity, AVG(pv7_score) AS avg_pv7_score,
                AVG(q_delta) AS avg_q_delta, AVG(stability_delta) AS avg_stability_delta
                FROM crystal_states"""
            ).fetchone()
            temporal_rows = conn.execute(
                """SELECT temporal_status, COUNT(*) AS c FROM crystal_states
                GROUP BY temporal_status ORDER BY c DESC"""
            ).fetchall()
            context_rows = conn.execute(
                """SELECT context_scope, context_key, COUNT(*) AS c FROM crystal_states
                WHERE context_key IS NOT NULL AND context_key != ''
                GROUP BY context_scope, context_key ORDER BY c DESC LIMIT 20"""
            ).fetchall()
        qualia_bus = self._qualia_doctor()
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
                "qualia_experiences": int((qualia_bus.get("counts") or {}).get("qualia_experiences", 0) or 0),
            },
            "qualia_bus": qualia_bus,
            "crystal_quality": dict(crystal_quality) if crystal_quality else {},
            "crystal_temporal_status": [dict(row) for row in temporal_rows],
            "crystal_contexts": [dict(row) for row in context_rows],
            "model_usage": [dict(row) for row in model_rows],
            "model_events": [dict(row) for row in model_event_rows],
        }


    def _qualia_store(self) -> Any:
        from triade.qualia.store import QualiaStore
        return QualiaStore(db_path=self.db_path)

    def _qualia_doctor(self) -> dict[str, Any]:
        try:
            return self._qualia_store().doctor()
        except Exception as exc:
            return {"status": "missing_tables", "error": str(exc)}

    def store_qualia_experience(self, experience: Any) -> str:
        return self._qualia_store().store_experience(experience)

    def store_qualia_signal(self, signal: Any) -> str:
        return self._qualia_store().store_signal(signal)

    def store_qualia_central_packet(self, packet: Any) -> str:
        return self._qualia_store().store_central_packet(packet)

    def store_qualia_storage_packet(self, packet: Any) -> str:
        return self._qualia_store().store_storage_packet(packet)

    def store_qualia_state(self, state: Any) -> int:
        return self._qualia_store().store_state(state)

    def list_qualia_state(self, run_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        return self._qualia_store().list_states(run_id=run_id, limit=limit)

    def list_qualia_experiences(self, run_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return self._qualia_store().list_experiences(run_id=run_id, limit=limit)

    def _fetch_identity(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            core = conn.execute("SELECT key, value, category, confidence FROM identity_core ORDER BY id ASC").fetchall()
            auto = conn.execute("SELECT trait_key AS key, trait_value AS value, category, confidence FROM auto_identity WHERE status IN ('candidate', 'stable') ORDER BY confidence DESC").fetchall()
        results = [dict(row) for row in core]
        for row in auto:
            item = dict(row)
            item["source"] = "auto_identity"
            results.append(item)
        return results

    def _search_semantic(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        terms = self._terms(query)
        if not terms:
            return []
        like_clauses = " OR ".join(["value LIKE ? OR key LIKE ? OR domain LIKE ?" for _ in terms])
        params: list[str] = []
        for term in terms:
            pattern = f"%{term}%"
            params.extend([pattern, pattern, pattern])
        sql = f"""SELECT key, value, domain, source_ref, confidence, status
            FROM semantic_memory WHERE {like_clauses} ORDER BY confidence DESC LIMIT ?"""
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
        sql = f"""SELECT id, run_id, title, summary, tags, confidence, created_at
            FROM episodic_memory WHERE {like_clauses} ORDER BY id DESC LIMIT ?"""
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

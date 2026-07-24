"""Tests for schema migration robustness and data persistence across connections."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

SCHEMA_SQL = Path(__file__).resolve().parents[1] / "triade" / "memory" / "schemas.sql"
MIGRATION_003 = Path(__file__).resolve().parents[1] / "triade" / "memory" / "migrations" / "003_living_workers.sql"
MIGRATION_005 = Path(__file__).resolve().parents[1] / "triade" / "memory" / "migrations" / "005_triade_os.sql"


def _create_full_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    conn.executescript(MIGRATION_003.read_text(encoding="utf-8"))
    conn.executescript(MIGRATION_005.read_text(encoding="utf-8"))
    conn.close()


class TestSchemaMigration:
    def test_migration_adds_activation_type_to_old_schema(self, tmp_path: Path) -> None:
        db = tmp_path / "old.db"
        conn = sqlite3.connect(db)
        conn.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
        conn.executescript(MIGRATION_003.read_text(encoding="utf-8"))
        conn.close()

        conn2 = sqlite3.connect(db)
        conn2.execute("ALTER TABLE neuron_activity DROP COLUMN activation_type")
        conn2.commit()
        cols_before = {row[1] for row in conn2.execute("PRAGMA table_info(neuron_activity)").fetchall()}
        conn2.close()

        from triade.os.neuron_scheduler import NeuronScheduler
        NeuronScheduler(db_path=db)

        conn3 = sqlite3.connect(db)
        cols_after = {row[1] for row in conn3.execute("PRAGMA table_info(neuron_activity)").fetchall()}
        conn3.close()
        assert "activation_type" in cols_after

    def test_neuron_scheduler_inserts_after_migration(self, tmp_path: Path) -> None:
        db = tmp_path / "migrated.db"
        _create_full_db(db)

        from triade.os.neuron_scheduler import NeuronScheduler
        scheduler = NeuronScheduler(db_path=db)

        conn = sqlite3.connect(db)
        conn.execute(
            """INSERT INTO neurons (name, mission, domain, status, rules, triggers,
            inputs_allowed, outputs_allowed, forbidden_actions, success_metrics,
            evidence_required, activation_policy, contract_json, created_at)
            VALUES (?, ?, ?, ?, '[]', '[]', '[]', '[]', '[]', '[]', '[]', '{}', '{}', datetime('now'))""",
            ("MigratedNeuron", "Mission", "test", "experimental"),
        )
        conn.commit()
        nid = conn.execute("SELECT id FROM neurons WHERE name = 'MigratedNeuron'").fetchone()[0]
        conn.close()

        scheduler.record_activation(nid, duration_ms=1000, success=True)

        conn2 = sqlite3.connect(db)
        conn2.row_factory = sqlite3.Row
        row = conn2.execute(
            "SELECT activation_type FROM neuron_activity WHERE neuron_id = ?", (nid,)
        ).fetchone()
        conn2.close()
        assert row is not None
        assert row["activation_type"] == "scheduled"

    def test_idempotent_migration(self, tmp_path: Path) -> None:
        db = tmp_path / "idempotent.db"
        _create_full_db(db)
        from triade.os.neuron_scheduler import NeuronScheduler
        s1 = NeuronScheduler(db_path=db)
        s2 = NeuronScheduler(db_path=db)
        conn = sqlite3.connect(db)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "neuron_activity" in tables
        assert "neuron_priority_log" in tables


class TestDataPersistence:
    def test_neuron_scheduler_persistence_across_connections(self, tmp_path: Path) -> None:
        from triade.os.neuron_scheduler import NeuronScheduler
        db = tmp_path / "persist.db"
        _create_full_db(db)
        scheduler = NeuronScheduler(db_path=db)

        conn = sqlite3.connect(db)
        conn.execute(
            """INSERT INTO neurons (name, mission, domain, status, rules, triggers,
            inputs_allowed, outputs_allowed, forbidden_actions, success_metrics,
            evidence_required, activation_policy, contract_json, created_at)
            VALUES (?, ?, ?, ?, '[]', '[]', '[]', '[]', '[]', '[]', '[]', '{}', '{}', datetime('now'))""",
            ("PersistNeuron", "Mission", "test", "experimental"),
        )
        conn.commit()
        nid = conn.execute("SELECT id FROM neurons WHERE name = 'PersistNeuron'").fetchone()[0]
        conn.close()

        scheduler.record_activation(nid, duration_ms=500, success=True)

        priorities = scheduler.compute_priorities()
        assert len(priorities) == 1
        assert priorities[0].neuron_name == "PersistNeuron"

        scheduler2 = NeuronScheduler(db_path=db)
        priorities2 = scheduler2.compute_priorities()
        assert len(priorities2) == 1

    def test_event_engine_persistence_across_connections(self, tmp_path: Path) -> None:
        from triade.os.event_engine import EventEngine
        db = tmp_path / "event_persist.db"
        _create_full_db(db)
        engine = EventEngine(db_path=db)

        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO worker_events (event_type, status, message, created_at) VALUES (?, ?, ?, datetime('now'))",
            ("error_recorded", "warning", "test persistence"),
        )
        conn.commit()
        conn.close()

        tasks = engine.scan()
        assert len(tasks) >= 1

        engine2 = EventEngine(db_path=db)
        last_id = engine2._get_state("last_processed_event_id")
        assert last_id is not None
        assert int(last_id) > 0

    def test_semantic_store_persistence(self, tmp_path: Path) -> None:
        from triade.memory.semantic_store import SemanticMemoryStore
        migration = "triade/memory/migrations/001_9A_semantic_memory.sql"
        db = tmp_path / "semantic_persist.db"
        store = SemanticMemoryStore(db_path=str(db), migration_path=migration)
        doc = store.upsert_document("Persistence test content", domain="test")
        assert doc.document_id

        store2 = SemanticMemoryStore(db_path=str(db), migration_path=migration)
        docs = store2.list_documents()
        assert len(docs) >= 1
        assert docs[0]["document_id"] == doc.document_id

    def test_constitution_enforcer_persistence(self, tmp_path: Path) -> None:
        from triade.constitution.enforcer import ConstitutionEnforcer
        db = tmp_path / "constitution_persist.db"
        enforcer = ConstitutionEnforcer(db_path=str(db))
        enforcer.check_article("central", 1, {"modifies_identity": False})

        enforcer2 = ConstitutionEnforcer(db_path=str(db))
        summary = enforcer2.article_summary()
        assert 1 in summary
        assert summary[1]["checks"]["pass"] >= 1

    def test_compression_consolidation_persistence(self, tmp_path: Path) -> None:
        from triade.memory.compression import MemoryConsolidator
        db = tmp_path / "compress_persist.db"
        _create_full_db(db)
        mc = MemoryConsolidator(db_path=str(db))
        mc.compress_episodes()

        mc2 = MemoryConsolidator(db_path=str(db))
        s = mc2.summary()
        assert isinstance(s, dict)

"""Tests de Qualia como estado vivo integrado."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.core.life_pulse import LifePulseEngine
from triade.core.qualia import QualiaEngine


def make_qualia_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    migration = Path("triade/memory/migrations/001_9A_semantic_memory.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
        conn.executescript(migration)
        run_id = "qualia-run-1"
        conn.execute(
            "INSERT INTO runs (run_id, source, user_input, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, "test", "qualia pulso memoria semantica", "ok", "2026-06-05"),
        )
        conn.execute(
            "INSERT INTO signal_states (run_id, intent, tone, urgency, risk, pv7, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, "conversation", "constructive", "medium", "low", "{}", "[]"),
        )
        conn.execute(
            "INSERT INTO crystal_states (run_id, q_crystal, stability, temporal_status) VALUES (?, ?, ?, ?)",
            (run_id, 0.62, 0.84, "stable"),
        )
        conn.execute("INSERT INTO verification_reports (run_id, status) VALUES (?, ?)", (run_id, "ok"))
        conn.execute(
            "INSERT INTO model_events (run_id, role, provider, model_name, ok, quality_score) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, "central", "template", "template-fallback", 0, 0.75),
        )
        conn.execute(
            "INSERT INTO model_events (run_id, role, provider, model_name, ok, quality_score) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, "hypothalamus", "rules", "rules-fallback", 0, 0.75),
        )
        conn.execute(
            "INSERT INTO episodic_memory (run_id, title, content, summary, tags) VALUES (?, ?, ?, ?, ?)",
            (run_id, "Qualia", "Usuario privado\nRespuesta", "Resumen", "triade"),
        )
        conn.execute(
            """INSERT INTO semantic_documents
            (document_id, content, normalized_content, content_hash, domain, source_type, source_ref, metadata, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("sem-stable-1", "Pulso vivo documentado", "pulso vivo documentado", "hash1", "core", "manual", "test:qualia", "{}", "stable"),
        )
        conn.execute(
            """INSERT INTO semantic_embeddings
            (document_id, embedding_model, vector_json, dimensions, vector_norm, status)
            VALUES (?, ?, ?, ?, ?, ?)""",
            ("sem-stable-1", "test-embed", "[0.1, 0.2]", 2, 0.2236, "stored"),
        )
    return db_path


def test_qualia_aligns_semantic_memory_with_life_pulse(tmp_path: Path) -> None:
    db_path = make_qualia_db(tmp_path)
    life = LifePulseEngine(db_path=db_path, runs_dir=tmp_path / "runs", interval_seconds=5, reflection_limit=10)
    qualia = QualiaEngine(db_path=db_path, life_pulse=life)

    payload = qualia.snapshot(refresh_life=True)

    assert payload["mode"] == "qualia"
    assert payload["semantic_alignment"]["has_stable_semantic_memory"] is True
    assert payload["semantic_alignment"]["embeddings"] == 1
    assert payload["senses"]["mode"] == "internal_senses"
    assert "sentido vital" in payload["senses"]["pulse"]["meaning"]
    assert "Pulso vivo" in {item["name"] for item in payload["organs"]}
    assert payload["life_pulse"]["counters"]["cycles"] == 1
    assert payload["triade_map"]["qualia"].startswith("integra")
    assert "sentidos internos" in payload["triade_map"]["pulso_vivo"]
    assert payload["identity"]["entity_name"] == "Tríade Ω"
    assert "Toda alma cuenta" in payload["identity"]["ethics"]
    assert "qualia_bus" in payload
    assert payload["qualia_bus"]["status"] in {"ok", "empty", "missing_tables"}

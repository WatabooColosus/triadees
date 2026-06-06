"""Tests de continuidad semántica real."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.core.runner import TriadeRunner
from triade.memory.semantic_continuity import LOCAL_HASH_MODEL, SemanticContinuity, local_hash_embedding


def test_local_hash_embedding_is_deterministic_and_nonzero() -> None:
    first = local_hash_embedding("memoria continua real")
    second = local_hash_embedding("memoria continua real")

    assert first == second
    assert len(first) == 64
    assert any(value != 0.0 for value in first)


def test_runner_creates_semantic_document_and_embedding_for_run(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runner = TriadeRunner(runs_dir=tmp_path / "runs", db_path=db_path, use_ollama=False)

    result = runner.run("La memoria semántica debe ser continua y real", source="test")

    continuity = result["memory_diff"]["semantic_continuity"]
    assert continuity["status"] == "ok"
    assert continuity["document"]["source_ref"] == f"run:{result['run_id']}"
    assert continuity["document"]["status"] == "candidate"
    assert continuity["embedding_event"]["ok"] is True
    assert continuity["embedding_event"]["model"] == LOCAL_HASH_MODEL

    with sqlite3.connect(db_path) as conn:
        docs = conn.execute("SELECT COUNT(*) FROM semantic_documents").fetchone()[0]
        embeddings = conn.execute("SELECT COUNT(*) FROM semantic_embeddings").fetchone()[0]
    assert docs >= 1
    assert embeddings >= 1


def test_semantic_continuity_backfills_recent_runs(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runner = TriadeRunner(runs_dir=tmp_path / "runs", db_path=db_path, use_ollama=False)
    runner.run("Run para backfill semántico", source="test")

    result = SemanticContinuity(db_path=db_path, auto_ollama_embed=False).backfill_recent_runs(limit=5)

    assert result["status"] == "ok"
    assert result["processed"] >= 1
    assert result["embeddings_ok"] >= 1
    doctor = SemanticContinuity(db_path=db_path, auto_ollama_embed=False).doctor()
    assert doctor["conversation_run_documents"] >= 1
    assert doctor["store"]["embeddings"] >= 1

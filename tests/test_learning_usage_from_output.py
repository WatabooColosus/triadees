"""Tests de conexión entre aprendizaje y uso en runs."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from triade.core.run_learning_usage import (
    _compute_outcome_score,
    record_learning_usage_from_output,
)
from triade.learning.pipeline import LearningPipeline


def make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
    return db_path


def test_record_usage_requires_explicit_candidate_and_measured_evidence(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    pipeline = LearningPipeline(db_path=db_path)
    candidate = pipeline.ingest(
        content="Test learning content about edge computing",
        source_type="conversation",
        source_ref="run:run-001",
        title="Edge computing learning",
        domain="federation_android_edge",
        risk_level="low",
    )
    pipeline.evaluate(candidate["candidate_id"])
    pipeline.verify(candidate["candidate_id"])

    output = SimpleNamespace(
        response="This response discusses edge computing patterns on Android devices",
        status="ok",
        model_ok=True,
        memory_diff={
            "used_learning_candidate_ids": [candidate["candidate_id"]],
            "learning_outcome_score": 0.82,
            "learning_outcome_evidence_ref": "evaluation:run-002",
        },
    )
    memory = SimpleNamespace(verification_status="ok")

    result = record_learning_usage_from_output(
        run_id="run-002",
        output_packet=output,
        memory_packet=memory,
        db_path=db_path,
    )

    assert result["candidates_marked"] >= 1
    assert result["outcome_score"] > 0.0


def test_record_usage_no_match_returns_zero(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    pipeline = LearningPipeline(db_path=db_path)
    candidate = pipeline.ingest(
        content="Completamente unrelated topic",
        source_type="conversation",
        source_ref="run:run-001",
        title="Unrelated",
        domain="unrelated_domain",
        risk_level="low",
    )
    pipeline.evaluate(candidate["candidate_id"])
    pipeline.verify(candidate["candidate_id"])

    output = SimpleNamespace(
        response="This is about something totally different with no overlap whatsoever",
        status="ok",
        model_ok=True,
    )
    memory = SimpleNamespace(verification_status="ok")

    result = record_learning_usage_from_output(
        run_id="run-003",
        output_packet=output,
        memory_packet=memory,
        db_path=db_path,
    )

    assert result["candidates_marked"] == 0


def test_record_usage_empty_response(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    output = SimpleNamespace(response="", status="ok", model_ok=True)
    memory = SimpleNamespace(verification_status="ok")

    result = record_learning_usage_from_output(
        run_id="run-004",
        output_packet=output,
        memory_packet=memory,
        db_path=db_path,
    )
    assert result["candidates_marked"] == 0


def test_outcome_score_requires_measurement(tmp_path: Path) -> None:
    output = SimpleNamespace(response="A" * 100, status="ok", model_ok=True, memory_diff={})
    memory = SimpleNamespace(verification_status="ok")
    score = _compute_outcome_score(output, memory)
    assert score == 0.0


def test_outcome_score_reads_explicit_measurement(tmp_path: Path) -> None:
    output = SimpleNamespace(
        response="Blocked",
        status="blocked",
        model_ok=False,
        memory_diff={
            "learning_outcome_score": 0.2,
            "learning_outcome_evidence_ref": "evaluation:blocked",
        },
    )
    memory = SimpleNamespace(verification_status="blocked")
    score = _compute_outcome_score(output, memory)
    assert score == 0.2


def test_outcome_score_dict_input() -> None:
    output = {
        "response": "A" * 100,
        "status": "ok",
        "memory_diff": {
            "learning_outcome_score": 0.75,
            "learning_outcome_evidence_ref": "evaluation:dict",
        },
    }
    memory = None
    score = _compute_outcome_score(output, memory)
    assert score == 0.75


def test_heuristic_overlap_is_observed_but_never_counted(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    pipeline = LearningPipeline(db_path=db_path)
    candidate = pipeline.ingest(
        content="edge computing android devices",
        source_type="conversation",
        source_ref="run:source",
        title="Edge computing",
        domain="edge",
        risk_level="low",
    )
    pipeline.evaluate(candidate["candidate_id"])
    pipeline.verify(candidate["candidate_id"])
    output = SimpleNamespace(response="edge computing android devices", memory_diff={})
    result = record_learning_usage_from_output("run-observation", output, None, db_path)
    assert result["candidates_marked"] == 0
    assert result["heuristic_observations"][0]["counted"] is False


def test_record_usage_does_not_consolidate(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    pipeline = LearningPipeline(db_path=db_path)
    candidate = pipeline.ingest(
        content="Test content for consolidation check",
        source_type="conversation",
        source_ref="run:run-001",
        title="Consolidation test",
        domain="test",
        risk_level="low",
    )
    pipeline.evaluate(candidate["candidate_id"])
    pipeline.verify(candidate["candidate_id"])

    output = SimpleNamespace(
        response="Test content for consolidation check",
        status="ok",
        model_ok=True,
    )
    memory = SimpleNamespace(verification_status="ok")

    record_learning_usage_from_output(
        run_id="run-005",
        output_packet=output,
        memory_packet=memory,
        db_path=db_path,
    )

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status FROM learning_queue WHERE candidate_id = ?",
            (candidate["candidate_id"],),
        ).fetchone()
    assert row is not None
    assert row["status"] in ("internally_checked", "validated_in_runs")
    assert row["status"] != "consolidated"

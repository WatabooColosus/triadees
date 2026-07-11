from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.learning.pipeline import LearningPipeline
from triade.memory.semantic_governance import SemanticMemoryGovernance
from triade.memory.semantic_store import SemanticMemoryStore
from triade.regression.learning_rollback import register_learning_rollback
from triade.regression.rollback import RollbackExecutor


def make_consolidated_learning(db_path: Path, label: str) -> tuple[str, str]:
    pipeline = LearningPipeline(db_path=db_path)
    candidate = pipeline.ingest(
        content=f"Conocimiento verificable {label}",
        source_type="document",
        source_ref=f"doc://{label}",
        title=label,
        domain="testing",
    )
    candidate_id = str(candidate["candidate_id"])
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE learning_queue SET status = 'consolidated' WHERE candidate_id = ?",
            (candidate_id,),
        )
    store = SemanticMemoryStore(db_path=db_path)
    document = store.upsert_document(
        content=f"Conocimiento verificable {label}",
        domain="testing",
        source_type="learning_pipeline",
        source_ref=f"doc://{label}",
        metadata={"learning_candidate_id": candidate_id},
        status="candidate",
    )
    governance = SemanticMemoryGovernance(db_path=db_path)
    governance.transition_document(document.document_id, "experimental", reason="test", approved_by="test")
    governance.transition_document(document.document_id, "stable", reason="test", approved_by="test")
    return candidate_id, document.document_id


def test_learning_rollback_retires_failed_candidate_and_preserves_stable_target(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    stable_id, stable_document_id = make_consolidated_learning(db_path, "stable")
    failed_id, failed_document_id = make_consolidated_learning(db_path, "failed")
    executor = RollbackExecutor(db_path)
    register_learning_rollback(executor, db_path)
    executor.plan(
        rollback_id="rollback-learning-1",
        capability="learning",
        candidate_id=failed_id,
        report_id="report-critical",
        target={
            "subject_id": stable_id,
            "evaluation_id": "eval-stable",
            "suite_id": "learning-critical",
            "suite_version": "1.0.0",
        },
        reason="critical regression",
        requested_by="central",
    )

    result = executor.execute("rollback-learning-1")

    assert result.status == "applied"
    assert result.after_state["subject_id"] == stable_id
    assert result.after_state["retired_candidate_status"] == "archived"
    assert result.after_state["retired_semantic_status"] == "rejected"
    store = SemanticMemoryStore(db_path=db_path)
    assert store.get_document(stable_document_id)["status"] == "stable"
    assert store.get_document(failed_document_id)["status"] == "rejected"


def test_learning_rollback_rejects_non_consolidated_target(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    pipeline = LearningPipeline(db_path=db_path)
    target = pipeline.ingest("target candidate", source_ref="doc://target")
    failed_id, _ = make_consolidated_learning(db_path, "failed")
    executor = RollbackExecutor(db_path)
    register_learning_rollback(executor, db_path)
    executor.plan(
        rollback_id="rollback-learning-2",
        capability="learning",
        candidate_id=failed_id,
        report_id="report-critical",
        target={
            "subject_id": target["candidate_id"],
            "evaluation_id": "eval-target",
            "suite_id": "learning-critical",
            "suite_version": "1.0.0",
        },
        reason="critical regression",
        requested_by="central",
    )

    result = executor.execute("rollback-learning-2")

    assert result.status == "failed"
    assert "no está consolidated" in (result.error or "")


def test_learning_rollback_rejects_same_candidate_as_target(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    candidate_id, _ = make_consolidated_learning(db_path, "same")
    executor = RollbackExecutor(db_path)
    register_learning_rollback(executor, db_path)
    executor.plan(
        rollback_id="rollback-learning-3",
        capability="learning",
        candidate_id=candidate_id,
        report_id="report-critical",
        target={
            "subject_id": candidate_id,
            "evaluation_id": "eval-same",
            "suite_id": "learning-critical",
            "suite_version": "1.0.0",
        },
        reason="critical regression",
        requested_by="central",
    )

    result = executor.execute("rollback-learning-3")

    assert result.status == "failed"
    assert "no puede ser el target estable" in (result.error or "")

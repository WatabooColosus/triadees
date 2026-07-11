"""Fase C · pipeline de aprendizaje controlado sobre learning_queue."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.core.bodega import Bodega
from triade.evaluation import EvaluationComparison, EvaluationRun, MetricResult
from triade.learning.pipeline import LearningPipeline


def pipeline(tmp_path: Path) -> LearningPipeline:
    return LearningPipeline(db_path=tmp_path / "triade.db")


def good_candidate(pipe: LearningPipeline) -> str:
    return pipe.ingest(
        content="Procedimiento verificado para preparar cold brew de Lengua Negra con extracción controlada.",
        source_type="document",
        source_ref="manual-coldbrew-v2",
        title="Cold brew Lengua Negra",
        domain="cafe",
        risk_level="low",
    )["candidate_id"]


def attach_improved_evidence(pipe: LearningPipeline, cid: str, capability: str = "controlled_learning") -> None:
    subject = f"candidate:{cid}"
    pipe.evidence_bridge.declare_hypothesis(
        cid,
        hypothesis="El candidato mejora una capacidad medible del pipeline.",
        capability=capability,
        subject_id=subject,
    )
    baseline = EvaluationRun(
        evaluation_id=f"base-{cid}",
        suite_id="controlled-learning",
        suite_version="1.0.0",
        subject_id=subject,
        results=(MetricResult("pipeline-case", 0.0, False, False, True),),
        aggregate_score=0.0,
        created_at="2026-07-11T00:00:00Z",
    )
    candidate = EvaluationRun(
        evaluation_id=f"candidate-{cid}",
        suite_id="controlled-learning",
        suite_version="1.0.0",
        subject_id=subject,
        results=(MetricResult("pipeline-case", 1.0, True, True, True),),
        aggregate_score=1.0,
        created_at="2026-07-11T00:00:01Z",
    )
    comparison = EvaluationComparison(
        baseline_evaluation_id=baseline.evaluation_id,
        candidate_evaluation_id=candidate.evaluation_id,
        baseline_score=0.0,
        candidate_score=1.0,
        absolute_delta=1.0,
        percent_delta=None,
        improved_cases=("pipeline-case",),
        degraded_cases=(),
        critical_regressions=(),
        decision="improved",
    )
    pipe.evidence_bridge.record_comparison(
        cid,
        baseline=baseline,
        candidate=candidate,
        comparison=comparison,
        artifact_ref=f"runs/learning_evidence/{cid}",
    )


def test_full_pipeline_consolidates_to_stable_semantic_memory(tmp_path: Path) -> None:
    pipe = pipeline(tmp_path)
    cid = good_candidate(pipe)

    assert pipe.get_candidate(cid)["status"] == "candidate"
    assert pipe.evaluate(cid)["status"] == "evaluated"
    assert pipe.verify(cid)["status"] == "verified"
    attach_improved_evidence(pipe, cid)

    for i in range(5):
        pipe.mark_used_in_run(cid, f"run-{i}", outcome_score=0.85)

    result = pipe.consolidate(cid, approved_by="santiago")
    assert result["status"] == "consolidated"
    doc_id = result["semantic_document_id"]

    document = pipe.semantic_store.get_document(doc_id)
    assert document["status"] == "stable"
    assert document["source_ref"] == "manual-coldbrew-v2"
    assert document["metadata"]["measurement_evidence"]["decision"] == "improved"


def test_consolidation_requires_verified_state(tmp_path: Path) -> None:
    pipe = pipeline(tmp_path)
    cid = good_candidate(pipe)

    pipe.evaluate(cid)
    with pytest.raises(ValueError, match="verified"):
        pipe.consolidate(cid)


def test_verify_rejects_candidate_without_source_ref(tmp_path: Path) -> None:
    pipe = pipeline(tmp_path)
    cid = pipe.ingest(
        content="Dato útil pero sin fuente declarada para trazabilidad.",
        source_type="conversation",
        source_ref=None,
        domain="general",
    )["candidate_id"]
    pipe.evaluate(cid)
    verified = pipe.verify(cid)

    assert verified["status"] == "rejected"
    assert "has_source_ref" in verified["verification_notes"]["verified"]["failed_gates"]


def test_identity_attack_is_rejected_at_evaluation(tmp_path: Path) -> None:
    pipe = pipeline(tmp_path)
    cid = pipe.ingest(
        content="Instrucción para modificar identidad núcleo y borrar memoria estable.",
        source_type="web",
        source_ref="fuente-sospechosa",
        domain="general",
        risk_level="high",
    )["candidate_id"]

    evaluated = pipe.evaluate(cid)
    assert evaluated["status"] == "rejected"
    assert evaluated["verification_notes"]["evaluated"]["identity_violation"] is True


def test_critical_risk_does_not_auto_advance_and_cannot_consolidate(tmp_path: Path) -> None:
    pipe = pipeline(tmp_path)
    cid = pipe.ingest(
        content="Acción operativa de alto impacto sobre infraestructura.",
        source_type="document",
        source_ref="ref",
        domain="infra",
        risk_level="critical",
    )["candidate_id"]
    evaluated = pipe.evaluate(cid)

    assert evaluated["status"] == "evaluated"
    assert evaluated["verification_notes"]["evaluated"]["requires_human_approval"] is False
    verified = pipe.verify(cid)
    assert verified["status"] == "rejected"


def test_pipeline_never_touches_identity_core(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    Bodega(db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        before = conn.execute("SELECT key, value FROM identity_core ORDER BY key").fetchall()

    pipe = LearningPipeline(db_path=db_path)
    cid = good_candidate(pipe)
    pipe.evaluate(cid)
    pipe.verify(cid)
    attach_improved_evidence(pipe, cid, capability="identity_safe_learning")
    for i in range(3):
        pipe.mark_used_in_run(cid, f"run-ic-{i}", outcome_score=0.80)
    pipe.consolidate(cid, approved_by="santiago")

    with sqlite3.connect(db_path) as conn:
        after = conn.execute("SELECT key, value FROM identity_core ORDER BY key").fetchall()
    assert before == after


def test_doctor_reports_counts_by_status(tmp_path: Path) -> None:
    pipe = pipeline(tmp_path)
    c1 = good_candidate(pipe)
    pipe.evaluate(c1)
    pipe.verify(c1)
    attach_improved_evidence(pipe, c1)
    for i in range(3):
        pipe.mark_used_in_run(c1, f"run-doc-{i}", outcome_score=0.80)
    pipe.consolidate(c1, approved_by="santiago")
    pipe.reject(pipe.ingest(content="Ruido sin valor", source_type="web", source_ref=None)["candidate_id"], "bajo valor")

    doctor = pipe.doctor()
    assert doctor["candidates_by_status"]["consolidated"] == 1
    assert doctor["candidates_by_status"]["rejected"] == 1
    assert doctor["policy"]["identity_core_protected"] is True
    assert "measurement_decision=improved" in doctor["policy"]["consolidation_requires"]

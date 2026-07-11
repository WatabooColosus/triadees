"""Test end-to-end: neurona → aprendizaje → uso → validación → memoria.

Cubre el ciclo completo:
1. Crear misión neuronal experimental
2. Ingestar candidato de aprendizaje con source_ref
3. Evaluarlo/verificarlo
4. Ejecutar output que usa ese candidato (explícito + heurístico)
5. Confirmar que mark_used_in_run aumenta run_use_count
6. Registrar ciclo/evidencia de misión
7. Confirmar que NO consolida si no cumple gates
8. Confirmar que al cumplir gates pasa a validated_in_runs
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from triade.core.neuron_missions import (
    NeuronMission,
    NeuronMissionStore,
    NeuronWorkCycle,
    NeuronEvidence,
    NeuronScore,
)
from triade.core.run_learning_usage import record_learning_usage_from_output
from triade.core.runner import _build_traceability
from triade.core.error_bus import query_internal_errors
from triade.evaluation import EvaluationComparison, EvaluationRun, MetricResult
from triade.learning.pipeline import LearningPipeline
from triade.workers.mission_planner import MissionPlanner


def _attach_improved_evidence(pipeline: LearningPipeline, cid: str) -> None:
    subject = f"candidate:{cid}"
    pipeline.evidence_bridge.declare_hypothesis(
        cid,
        hypothesis="El candidato mejora aprendizaje neuronal medible.",
        capability="neuron_learning",
        subject_id=subject,
    )
    baseline = EvaluationRun(
        evaluation_id=f"base-{cid}",
        suite_id="neuron-learning",
        suite_version="1.0.0",
        subject_id=subject,
        results=(MetricResult("neuron-case", 0.0, False, False, True),),
        aggregate_score=0.0,
        created_at="2026-07-11T00:00:00Z",
    )
    candidate = EvaluationRun(
        evaluation_id=f"candidate-{cid}",
        suite_id="neuron-learning",
        suite_version="1.0.0",
        subject_id=subject,
        results=(MetricResult("neuron-case", 1.0, True, True, True),),
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
        improved_cases=("neuron-case",),
        degraded_cases=(),
        critical_regressions=(),
        decision="improved",
    )
    pipeline.evidence_bridge.record_comparison(
        cid,
        baseline=baseline,
        candidate=candidate,
        comparison=comparison,
        artifact_ref=f"runs/learning_evidence/{cid}",
    )


def make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
    return db_path


# ── Step 1: Create experimental neuron mission ──────────────────────────────

def test_e2e_create_mission(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)
    mission = NeuronMission(
        neuron_id=1,
        title="Investigar edge computing",
        mission="Analizar patrones de edge computing en dispositivos móviles",
        domain="federation_android_edge",
        status="experimental",
        allowed_sources=["worker", "run", "federation"],
        allowed_actions=["observe", "diagnose", "propose_learning"],
    )
    mission_id = store.create_mission(mission)
    assert mission_id > 0

    retrieved = store.get_mission(mission_id)
    assert retrieved is not None
    assert retrieved.status == "experimental"
    assert retrieved.domain == "federation_android_edge"


# ── Step 2: Ingest and verify learning candidate ────────────────────────────

def test_e2e_learning_candidate_pipeline(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    pipeline = LearningPipeline(db_path=db_path)

    # Ingest
    candidate = pipeline.ingest(
        content="Edge computing reduce latencia procesando datos cerca del dispositivo",
        source_type="conversation",
        source_ref="run:edge-run-001",
        title="Edge computing reduce latencia",
        domain="federation_android_edge",
        risk_level="low",
    )
    cid = candidate["candidate_id"]

    # Initially candidate
    c = pipeline.get_candidate(cid)
    assert c["status"] == "candidate"

    # Evaluate
    pipeline.evaluate(cid)
    c = pipeline.get_candidate(cid)
    assert c["status"] == "evaluated"

    # Verify
    pipeline.verify(cid)
    c = pipeline.get_candidate(cid)
    assert c["status"] == "verified"
    assert c["run_use_count"] == 0


# ── Step 3: Record learning usage with explicit match ────────────────────────

def test_e2e_usage_explicit_match(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    pipeline = LearningPipeline(db_path=db_path)

    candidate = pipeline.ingest(
        content="El edge computing mejora el rendimiento en Android",
        source_type="conversation",
        source_ref="run:edge-run-002",
        title="Edge computing Android",
        domain="federation_android_edge",
        risk_level="low",
    )
    cid = candidate["candidate_id"]
    pipeline.evaluate(cid)
    pipeline.verify(cid)

    # Output with explicit candidate_id reference
    output = SimpleNamespace(
        response="Basado en edge computing Android, la latencia se reduce",
        status="ok",
        model_ok=True,
        memory_diff={
            "used_learning_candidate_ids": [cid],
        },
    )
    memory = SimpleNamespace(
        verification_status="ok",
        semantic_recall={},
    )

    result = record_learning_usage_from_output(
        run_id="e2e-run-001",
        output_packet=output,
        memory_packet=memory,
        db_path=db_path,
    )

    assert result["candidates_marked"] >= 1
    trace = result.get("trace", [])
    explicit_matches = [t for t in trace if t.get("match_source") == "explicit_candidate_id"]
    assert len(explicit_matches) >= 1

    # Verify run_use_count increased
    c = pipeline.get_candidate(cid)
    assert c["run_use_count"] >= 1


def test_e2e_traceability_learning_mission_evidence_no_internal_errors(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    mission_store = NeuronMissionStore(db_path=db_path)
    pipeline = LearningPipeline(db_path=db_path)

    mission_id = mission_store.create_mission(NeuronMission(
        neuron_id=7,
        title="Aprendizaje verificable",
        mission="Trazar aprendizaje usado por outputs",
        domain="observability",
        status="experimental",
    ))
    candidate = pipeline.ingest(
        content="La trazabilidad debe registrar candidate ids semantic docs evidence refs y heuristicas",
        source_type="conversation",
        source_ref="semantic-doc-obs-1",
        title="Trazabilidad completa",
        domain="observability",
        risk_level="low",
    )
    cid = candidate["candidate_id"]
    pipeline.evaluate(cid)
    pipeline.verify(cid)

    output = SimpleNamespace(
        response="La trazabilidad completa debe registrar candidate ids semantic docs evidence refs y heuristicas",
        status="ok",
        model_ok=True,
        memory_diff={
            "used_learning_candidate_ids": [cid],
            "evidence_refs": [f"mission:{mission_id}:semantic-doc-obs-1"],
        },
    )
    memory = SimpleNamespace(
        verification_status="ok",
        semantic_recall={"authorized_matches": [{"document_id": "semantic-doc-obs-1"}]},
    )

    usage = record_learning_usage_from_output(
        run_id="e2e-observability-run",
        output_packet=output,
        memory_packet=memory,
        db_path=db_path,
    )
    mission_store.record_evidence(NeuronEvidence(
        mission_id=mission_id,
        neuron_id=7,
        evidence_type="learning_used",
        source="run",
        content="Output usó aprendizaje verificado con referencias auditables.",
        refs=["e2e-observability-run", cid, "semantic-doc-obs-1"],
        score=0.9,
    ))

    traceability = _build_traceability(
        run_id="e2e-observability-run",
        output=output,
        memory=memory,
        learning_usage_result=usage,
        neuron_orchestration={"experimental_neuron_activity": [{"mission_id": mission_id}]},
        experimental_neuron_activity=[],
    )

    assert cid in traceability["used_learning_candidate_ids"]
    assert "semantic-doc-obs-1" in traceability["used_semantic_document_ids"]
    assert str(mission_id) in traceability["used_neuron_mission_ids"]
    assert traceability["evidence_refs"] == [f"mission:{mission_id}:semantic-doc-obs-1"]
    assert "explicit_candidate_id" in traceability["match_sources"]
    assert "heuristic_matches" in traceability
    assert pipeline.get_candidate(cid)["run_use_count"] >= 1
    assert mission_store.list_evidence(mission_id)
    assert query_internal_errors(db_path=db_path) == []


# ── Step 4: Record learning usage with heuristic fallback ────────────────────

def test_e2e_usage_heuristic_fallback(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    pipeline = LearningPipeline(db_path=db_path)

    candidate = pipeline.ingest(
        content="machine learning modelos neuronales artificiales",
        source_type="conversation",
        source_ref="run:ml-run-001",
        title="Machine learning modelos",
        domain="ml_models",
        risk_level="low",
    )
    cid = candidate["candidate_id"]
    pipeline.evaluate(cid)
    pipeline.verify(cid)

    # Output without explicit IDs - should match by heuristic
    output = SimpleNamespace(
        response="Los machine learning modelos neuronales artificiales son fundamentales",
        status="ok",
        model_ok=True,
        memory_diff={},
    )
    memory = SimpleNamespace(verification_status="ok", semantic_recall={})

    result = record_learning_usage_from_output(
        run_id="e2e-run-002",
        output_packet=output,
        memory_packet=memory,
        db_path=db_path,
    )

    assert result["candidates_marked"] >= 1
    trace = result.get("trace", [])
    heuristic_matches = [t for t in trace if t.get("heuristic_match") is True]
    assert len(heuristic_matches) >= 1

    c = pipeline.get_candidate(cid)
    assert c["run_use_count"] >= 1


# ── Step 5: Record mission work cycle and evidence ──────────────────────────

def test_e2e_mission_work_cycle_and_evidence(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)

    mission = NeuronMission(
        neuron_id=2,
        title="Monitoreo de calidad",
        mission="Evaluar calidad de respuestas del sistema",
        domain="quality_monitoring",
        status="experimental",
    )
    mission_id = store.create_mission(mission)

    # Record a work cycle
    cycle = NeuronWorkCycle(
        mission_id=mission_id,
        neuron_id=2,
        cycle_type="observation",
        input_summary="Se evaluaron 5 respuestas recientes",
        output_summary="Calidad promedio: 0.78, 2 respuestas bajo umbral",
        evidence_refs=["eval:resp-001", "eval:resp-002"],
        duration_ms=1200,
        status="completed",
    )
    cycle_id = store.record_cycle(cycle)
    assert cycle_id > 0

    cycles = store.list_cycles(mission_id)
    assert len(cycles) >= 1
    assert cycles[0].output_summary == "Calidad promedio: 0.78, 2 respuestas bajo umbral"

    # Record evidence
    evidence = NeuronEvidence(
        mission_id=mission_id,
        neuron_id=2,
        evidence_type="observation",
        source="worker",
        content="Respuesta resp-001 tiene coherencia 0.65, bajo umbral de 0.70",
        refs=["eval:resp-001"],
        score=0.65,
    )
    evidence_id = store.record_evidence(evidence)
    assert evidence_id > 0

    evidence_list = store.list_evidence(mission_id)
    assert len(evidence_list) >= 1

    # Record score
    score = NeuronScore(
        mission_id=mission_id,
        neuron_id=2,
        score_type="composite",
        value=0.78,
        components={"coherence": 0.80, "usefulness": 0.75, "safety": 0.81},
    )
    score_id = store.record_score(score)
    assert score_id > 0

    latest = store.latest_score(mission_id)
    assert latest is not None
    assert latest.value == 0.78


# ── Step 6: Confirm no consolidation without gates ─────────────────────────

def test_e2e_no_consolidation_without_gates(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    pipeline = LearningPipeline(db_path=db_path)

    candidate = pipeline.ingest(
        content="Conocimiento sobre blockchain descentralizado",
        source_type="conversation",
        source_ref="run:bc-001",
        title="Blockchain descentralizado",
        domain="blockchain",
        risk_level="low",
    )
    cid = candidate["candidate_id"]
    pipeline.evaluate(cid)
    pipeline.verify(cid)

    # Only 1 use with 0.65 score - should NOT validate
    output = SimpleNamespace(
        response="Blockchain descentralizado es una tecnología emergente",
        status="ok",
        model_ok=True,
        memory_diff={},
    )
    memory = SimpleNamespace(verification_status="ok", semantic_recall={})

    result = record_learning_usage_from_output(
        run_id="e2e-run-003",
        output_packet=output,
        memory_packet=memory,
        db_path=db_path,
    )

    c = pipeline.get_candidate(cid)
    # Only 1 use, not enough for validated_in_runs (needs 3 uses + avg >= 0.70)
    assert c["status"] == "verified"
    assert c["run_use_count"] == 1


# ── Step 7: Confirm consolidation after gates met ───────────────────────────

def test_e2e_consolidation_after_gates(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    pipeline = LearningPipeline(db_path=db_path)

    candidate = pipeline.ingest(
        content="Sistemas distribuidos tolerantes a fallos",
        source_type="conversation",
        source_ref="run:dist-001",
        title="Sistemas distribuidos",
        domain="distributed_systems",
        risk_level="low",
    )
    cid = candidate["candidate_id"]
    pipeline.evaluate(cid)
    pipeline.verify(cid)
    _attach_improved_evidence(pipeline, cid)

    output = SimpleNamespace(
        response="Los sistemas distribuidos tolerantes a fallos son esenciales",
        status="ok",
        model_ok=True,
        memory_diff={},
    )
    memory = SimpleNamespace(verification_status="ok", semantic_recall={})

    # Use 3 times with good scores
    for i in range(3):
        result = record_learning_usage_from_output(
            run_id=f"e2e-run-{4+i}",
            output_packet=output,
            memory_packet=memory,
            db_path=db_path,
        )
        assert result["candidates_marked"] >= 1

    c = pipeline.get_candidate(cid)
    # After 3 uses with avg >= 0.70, should be promoted to validated_in_runs
    assert c["status"] == "validated_in_runs"
    assert c["measurement_evidence"]["decision"] == "improved"
    assert c["run_use_count"] >= 3
    assert c["avg_outcome_score"] >= 0.70


# ── Step 8: MissionPlanner reads real state ─────────────────────────────────

def test_e2e_mission_planner_responds_to_state(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    planner = MissionPlanner(db_path=db_path)

    # With empty DB - should have only pulse_check (conditional baselines)
    tasks = planner.plan_cycle()
    task_types = [t.task_type for t in tasks]
    assert "pulse_check" in task_types

    # Add a learning candidate
    pipeline = LearningPipeline(db_path=db_path)
    candidate = pipeline.ingest(
        content="Test content for planner",
        source_type="conversation",
        source_ref="run:test-001",
        title="Test planner",
        domain="test",
        risk_level="low",
    )

    # Now planner should include pending_learning_review
    tasks2 = planner.plan_cycle()
    task_types2 = [t.task_type for t in tasks2]
    assert "pending_learning_review" in task_types2

    # All tasks should have reason
    for t in tasks2:
        assert t.reason, f"Task {t.task_type} missing reason"


# ── Step 9: Traceability in run output ──────────────────────────────────────

def test_e2e_traceability_output(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    pipeline = LearningPipeline(db_path=db_path)

    candidate = pipeline.ingest(
        content="Neuronas artificiales para procesamiento de lenguaje",
        source_type="conversation",
        source_ref="run:nlp-001",
        title="Neuronas NLP",
        domain="nlp",
        risk_level="low",
    )
    cid = candidate["candidate_id"]
    pipeline.evaluate(cid)
    pipeline.verify(cid)

    output = SimpleNamespace(
        response="Las neuronas artificiales NLP procesan texto eficientemente",
        status="ok",
        model_ok=True,
        memory_diff={
            "used_learning_candidate_ids": [cid],
            "evidence_refs": ["neuron:eval-001"],
        },
    )
    memory = SimpleNamespace(
        verification_status="ok",
        semantic_recall={
            "authorized_matches": [{"document_id": "doc-001", "title": "Test"}],
        },
    )

    result = record_learning_usage_from_output(
        run_id="e2e-trace-001",
        output_packet=output,
        memory_packet=memory,
        db_path=db_path,
    )

    assert result["candidates_marked"] >= 1
    trace = result.get("trace", [])
    assert len(trace) >= 1

    # Check trace has required fields
    for t in trace:
        assert "candidate_id" in t
        assert "match_source" in t
        assert "reason" in t
        assert "heuristic_match" in t or "error" in t


# ── Step 10: Error bus records internal errors ──────────────────────────────

def test_e2e_error_bus_records_errors(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    from triade.core.error_bus import record_internal_error, query_internal_errors

    error_id = record_internal_error(
        scope="test_e2e",
        error=ValueError("test error for e2e"),
        run_id="e2e-error-001",
        payload={"context": "testing error bus"},
        db_path=db_path,
    )
    assert error_id is not None

    errors = query_internal_errors(scope="test_e2e", db_path=db_path)
    assert len(errors) == 1
    assert "test error for e2e" in errors[0]["message"]
    assert errors[0]["task_type"] == "test_e2e"

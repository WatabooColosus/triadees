from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.core.bodega import Bodega
from triade.core.neuron_creator import NeuronCreator
from triade.core.neuron_registry import NeuronRegistry
from triade.evaluation import EvaluationComparison, EvaluationRun, MetricResult
from triade.learning.pipeline import LearningPipeline
from triade.learning.production_injection import ProductionKnowledgeInjector
from triade.neurons.education_resolver import NeuronEducationResolver
from triade.neurons.learning_router import NeuralLearningRouter
from triade.workers.mission_planner import MissionPlanner
from triade.workers.worker_loop import WorkerLoop

CONTENT = (
    "Para informes de auditoría usa siempre el marcador NEURONA-AUDIT-7319 "
    "antes de cualquier sección."
)
QUERY = "Prepara un informe de auditoría con su marcador"


def _improved_evidence(
    pipe: LearningPipeline, candidate_id: str, *, baseline_score: float
) -> None:
    subject = f"candidate:{candidate_id}"
    pipe.evidence_bridge.declare_hypothesis(
        candidate_id,
        hypothesis="El marcador mejora la exactitud medible del informe.",
        capability="audit_reporting",
        subject_id=subject,
    )
    baseline = EvaluationRun(
        evaluation_id=f"baseline-{candidate_id}",
        suite_id="audit-reporting",
        suite_version="1",
        subject_id=subject,
        results=(
            MetricResult("marker", baseline_score, baseline_score >= 0.8, "", CONTENT),
        ),
        aggregate_score=baseline_score,
        created_at="2026-08-11T00:00:00Z",
    )
    candidate = EvaluationRun(
        evaluation_id=f"candidate-{candidate_id}",
        suite_id="audit-reporting",
        suite_version="1",
        subject_id=subject,
        results=(MetricResult("marker", 1.0, True, CONTENT, CONTENT),),
        aggregate_score=1.0,
        created_at="2026-08-11T00:01:00Z",
    )
    comparison = EvaluationComparison(
        baseline_evaluation_id=baseline.evaluation_id,
        candidate_evaluation_id=candidate.evaluation_id,
        baseline_score=baseline_score,
        candidate_score=1.0,
        absolute_delta=1.0 - baseline_score,
        percent_delta=None,
        improved_cases=("marker",),
        degraded_cases=(),
        critical_regressions=(),
        decision="improved",
    )
    pipe.evidence_bridge.record_comparison(
        candidate_id,
        baseline=baseline,
        candidate=candidate,
        comparison=comparison,
        artifact_ref=f"measurement:{candidate_id}",
    )


def _prepared_db(tmp_path: Path, *, baseline_score: float) -> tuple[Path, str, int]:
    db = tmp_path / "triade.db"
    Bodega(db_path=db)
    registry = NeuronRegistry(db)
    spec = NeuronCreator().create(
        "neurona-auditora",
        "Preparar informes de auditoría verificables",
        "audit",
        success_metrics=["marcador correcto"],
        evidence_required=["Measurement Core"],
    )
    neuron_id = registry.register(
        spec,
        contract_payload={
            "domains": ["audit"],
            "capabilities": ["audit_reporting"],
            "learning_interests": ["informes", "auditoría", "marcador"],
            "authorized_knowledge_types": ["fact", "preference", "correction"],
        },
    )
    registry.update_status("neurona-auditora", "experimental")

    # Precomportamiento medido por los mismos dos productores que consume el
    # router: actividad neuronal y VerificationReport.
    with sqlite3.connect(db) as conn:
        for index in range(5):
            run_id = f"baseline-{index}"
            conn.execute(
                "INSERT INTO runs(run_id,source,user_input,status,created_at) VALUES(?,?,?,?,datetime('now','-1 day'))",
                (run_id, "pytest", QUERY, "completed"),
            )
            conn.execute(
                "INSERT INTO neuron_activity(neuron_id,run_id,activated,created_at) VALUES(?,?,1,datetime('now','-1 day'))",
                (neuron_id, run_id),
            )
            conn.execute(
                """INSERT INTO verification_reports
                (run_id,coherence_score,memory_score,safety_score,usefulness_score,
                 traceability_score,status,created_at) VALUES(?,?,?,?,?,?,?,datetime('now','-1 day'))""",
                (
                    run_id,
                    baseline_score,
                    baseline_score,
                    baseline_score,
                    baseline_score,
                    baseline_score,
                    "verified",
                ),
            )

    pipe = LearningPipeline(db)
    row = pipe.ingest(
        content=CONTENT,
        source_type="conversation",
        source_ref="run:run-A",
        title="Preferencia verificable de auditoría",
        domain="audit",
        risk_level="low",
    )
    candidate_id = str(row["candidate_id"])
    pipe.evaluate(candidate_id)
    pipe.verify(candidate_id)
    _improved_evidence(pipe, candidate_id, baseline_score=baseline_score)
    for index in range(3):
        pipe.mark_used_in_run(
            candidate_id,
            f"validation-{index}",
            outcome_score=0.95,
            evidence_ref=f"verification:validation-{index}",
        )
    pipe.consolidate(candidate_id, approved_by="governed-test-worker")
    return db, candidate_id, neuron_id


def _apply_five_runs(db: Path, *, score: float) -> list[dict]:
    injector = ProductionKnowledgeInjector(db)
    traces = []
    for index in range(5):
        run_id = f"run-B-{index}"
        injection = injector.build(QUERY, run_id=run_id)
        assert injection.used
        traces.append(
            injector.confirm_uses(
                injection,
                f"NEURONA-AUDIT-7319: informe {index}",
                run_id=run_id,
                outcome_score=score,
                outcome_evidence_ref=f"verification_report:{run_id}",
            )
        )
    return traces


def test_consolidado_nutre_neurona_y_mejora_causalmente(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIADE_NEURAL_LEARNING_ROUTING", "1")
    db, candidate_id, neuron_id = _prepared_db(tmp_path, baseline_score=0.50)

    task = next(
        item
        for item in MissionPlanner(db).plan_cycle("neural-e2e")
        if item.task_type == "neural_learning_distribution"
    )
    task_dir = tmp_path / "worker" / "neural-route"
    task_dir.mkdir(parents=True)
    route = WorkerLoop(
        db_path=db, runs_dir=tmp_path / "worker"
    )._neural_learning_distribution(
        type("Task", (), {"payload": task.payload})(),
        "neural-e2e",
        task_dir,
        type("Config", (), {})(),
    )
    assert route["neuron_id"] == neuron_id
    assert route["baseline_score"] == 0.50
    assert route["effect"] == "routed"
    assert route["status"] == "completed"
    assert route["effect_receipt"]["verified"] is True

    traces = _apply_five_runs(db, score=0.90)
    assert all(trace["confirmed"][0]["neuron_id"] == neuron_id for trace in traces)
    verdict = NeuronEducationResolver(db).resolve_once()
    assert verdict["decision"] == "improved"
    assignment = NeuralLearningRouter(db).history(neuron_id)[0]
    assert assignment["candidate_id"] == candidate_id
    assert assignment["status"] == "beneficial"
    assert assignment["use_count"] == 5
    assert assignment["outcome_score"] == 0.90


def test_conocimiento_inferior_se_revierte_y_deja_de_inyectarse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIADE_NEURAL_LEARNING_ROUTING", "1")
    db, candidate_id, neuron_id = _prepared_db(tmp_path, baseline_score=0.90)
    NeuralLearningRouter(db).route(candidate_id)
    _apply_five_runs(db, score=0.40)

    verdict = NeuronEducationResolver(db).resolve_once()
    assert verdict["decision"] == "degraded"
    assert verdict["rolled_back"] is True
    assignment = NeuralLearningRouter(db).history(neuron_id)[0]
    assert assignment["status"] == "rolled_back"
    injection = ProductionKnowledgeInjector(db).build(QUERY, run_id="after-rollback")
    assert candidate_id not in injection.injected_ids


def test_no_distribuye_sin_consolidacion_ni_evidencia(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    Bodega(db_path=db)
    row = LearningPipeline(db).ingest(
        content=CONTENT,
        source_type="conversation",
        source_ref="run:bad-A",
        title="Hipótesis todavía no validada",
        domain="audit",
        risk_level="low",
    )
    with pytest.raises(ValueError, match="requires_consolidated_knowledge"):
        NeuralLearningRouter(db).route(str(row["candidate_id"]))

    task_dir = tmp_path / "rejected"
    task_dir.mkdir()
    rejected = WorkerLoop(
        db_path=db, runs_dir=tmp_path / "worker"
    )._neural_learning_distribution(
        type("Task", (), {"payload": {"candidate_id": row["candidate_id"]}})(),
        "reject-e2e",
        task_dir,
        type("Config", (), {})(),
    )
    assert rejected["effect"] == "rejected"
    assert rejected["effect_receipt"]["verified"] is True
    assert (
        NeuralLearningRouter(db).rejections()[0]["candidate_id"] == row["candidate_id"]
    )

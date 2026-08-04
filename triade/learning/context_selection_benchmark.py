"""Experimento reproducible de selección de contexto aprendido.

Este módulo no activa una capacidad productiva nueva. Usa las rutas vivas de
LearningPipeline, LearningRetriever, Measurement Core y Regression Gate para
demostrar, con un benchmark versionado, si un candidato cambia una selección.
"""

from __future__ import annotations

import json
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from triade.evaluation import (
    BenchmarkCase,
    BenchmarkSuite,
    EvaluationRun,
    EvaluationRunner,
    compare_evaluations,
)
from triade.learning.pipeline import LearningPipeline
from triade.learning.retrieval import LearningRetriever
from triade.regression import MetricPolicy

SPLITS = ("train", "validation", "held_out", "adversarial", "regression")
CAPABILITY = "learning_context_selection"


@dataclass(frozen=True, slots=True)
class LoadedBenchmark:
    suite: BenchmarkSuite
    split_by_case: dict[str, str]
    source_by_case: dict[str, str]


def load_benchmark(directory: str | Path) -> LoadedBenchmark:
    root = Path(directory)
    cases: list[BenchmarkCase] = []
    split_by_case: dict[str, str] = {}
    source_by_case: dict[str, str] = {}
    versions: set[str] = set()
    for split in SPLITS:
        payload = json.loads((root / f"{split}.json").read_text(encoding="utf-8"))
        for item in payload:
            required = {
                "id",
                "input",
                "expected_output",
                "metric",
                "difficulty",
                "source",
                "split",
                "version",
            }
            missing = required - item.keys()
            if missing:
                raise ValueError(f"Caso {item.get('id')} incompleto: {sorted(missing)}")
            if item["split"] != split:
                raise ValueError(f"Split inconsistente en {item['id']}")
            if item["metric"] != "exact_match":
                raise ValueError(f"Métrica no soportada en {item['id']}")
            versions.add(str(item["version"]))
            case_id = str(item["id"])
            cases.append(
                BenchmarkCase(
                    case_id=case_id,
                    capability=CAPABILITY,
                    input_payload={"query": str(item["input"]), "split": split},
                    expected=str(item["expected_output"]),
                    critical=split == "regression",
                    tags=(split, str(item["difficulty"]), str(item["source"])),
                )
            )
            split_by_case[case_id] = split
            source_by_case[case_id] = str(item["source"])
    if len(versions) != 1:
        raise ValueError(f"El benchmark debe tener una versión única: {versions}")
    return LoadedBenchmark(
        suite=BenchmarkSuite(
            suite_id="learning-context-selection",
            version=versions.pop(),
            capability=CAPABILITY,
            cases=tuple(cases),
            description="Selección léxica segura de contexto sobre un candidato trazable.",
        ),
        split_by_case=split_by_case,
        source_by_case=source_by_case,
    )


def _split_scores(
    run: EvaluationRun, split_by_case: dict[str, str]
) -> dict[str, float]:
    scores: dict[str, list[float]] = {split: [] for split in SPLITS}
    for result in run.results:
        scores[split_by_case[result.case_id]].append(result.score)
    return {
        split: round(sum(values) / len(values), 6) if values else 0.0
        for split, values in scores.items()
    }


def run_retrieval_evaluation(
    loaded: LoadedBenchmark,
    *,
    db_path: str | Path,
    runs_dir: str | Path,
    subject_id: str,
    candidate_id: str | None,
    allowed_states: frozenset[str] | None = None,
) -> EvaluationRun:
    kwargs: dict[str, Any] = {"db_path": db_path}
    if allowed_states is not None:
        kwargs["allowed_states"] = allowed_states
    retriever = LearningRetriever(**kwargs)
    runner = EvaluationRunner(runs_dir=runs_dir)

    def evaluate(case: BenchmarkCase) -> str:
        decision = retriever.retrieve_decision(
            str(case.input_payload["query"]),
            run_id=f"{subject_id}:{case.case_id}",
            domain=CAPABILITY,
            only_candidate_ids={candidate_id} if candidate_id else set(),
        )
        return "relevant" if decision.injected_ids else "none"

    started = time.perf_counter()
    tracemalloc.start()
    run = runner.run(
        loaded.suite,
        subject_id=subject_id,
        evaluator=evaluate,
        metadata={"model": "deterministic-lexical-retriever", "tokens": 0},
    )
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    metadata = dict(run.metadata)
    metadata.update(
        {
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "peak_memory_bytes": peak,
            "split_scores": _split_scores(run, loaded.split_by_case),
        }
    )
    return EvaluationRun(
        evaluation_id=run.evaluation_id,
        suite_id=run.suite_id,
        suite_version=run.suite_version,
        subject_id=run.subject_id,
        results=run.results,
        aggregate_score=run.aggregate_score,
        created_at=run.created_at,
        metadata=metadata,
    )


def run_phase_1_experiment(
    benchmark_dir: str | Path,
    *,
    work_dir: str | Path,
    sha: str,
) -> dict[str, Any]:
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    db_path = work / "phase_1.db"
    evaluations_dir = work / "evaluations"
    loaded = load_benchmark(benchmark_dir)
    pipeline = LearningPipeline(db_path=db_path, enforce_model_policy=False)

    baseline = run_retrieval_evaluation(
        loaded,
        db_path=db_path,
        runs_dir=evaluations_dir,
        subject_id="phase-1-context-selection",
        candidate_id=None,
    )
    candidate = pipeline.ingest(
        content=(
            "Recuperación SQLite ante database locked o transacción bloqueada: "
            "ejecutar rollback, cerrar la conexión y reintentar con backoff."
        ),
        source_type="repo",
        source_ref=f"benchmark:{loaded.suite.suite_id}:{loaded.suite.version}@{sha}",
        title="Recuperación segura de bloqueo SQLite",
        domain=CAPABILITY,
        risk_level="low",
    )
    candidate_id = str(candidate["candidate_id"])
    pipeline.evaluate(candidate_id)
    pipeline.verify(candidate_id)
    treatment = run_retrieval_evaluation(
        loaded,
        db_path=db_path,
        runs_dir=evaluations_dir,
        subject_id="phase-1-context-selection",
        candidate_id=candidate_id,
    )
    comparison = compare_evaluations(
        baseline,
        treatment,
        critical_case_ids={
            case.case_id
            for case in loaded.suite.cases
            if loaded.split_by_case[case.case_id] == "regression"
        },
    )
    pipeline.evidence_bridge.declare_hypothesis(
        candidate_id,
        hypothesis="El candidato mejora la selección de contexto y generaliza fuera de train.",
        capability=CAPABILITY,
        subject_id="phase-1-context-selection",
        require_regression=True,
        require_generalization=True,
    )
    pipeline.evidence_bridge.record_comparison(
        candidate_id,
        baseline=baseline,
        candidate=treatment,
        comparison=comparison,
        artifact_ref=str(evaluations_dir),
    )
    policies = tuple(
        MetricPolicy(case.case_id, severity="critical")
        for case in loaded.suite.cases
        if loaded.split_by_case[case.case_id] in {"held_out", "regression"}
    )
    regression = pipeline.evidence_bridge.regression_gate.evaluate(
        report_id=f"regression-{candidate_id}",
        candidate_id=candidate_id,
        capability=CAPABILITY,
        baseline=baseline,
        candidate=treatment,
        policies=policies,
        metadata={"sha": sha},
    )
    pipeline.evidence_bridge.record_regression_report(candidate_id, regression)

    successful = [result for result in treatment.results if result.passed]
    positive = [result for result in successful if result.actual == "relevant"]
    for index, result in enumerate(positive[: pipeline.MIN_RUN_USES]):
        pipeline.mark_used_in_run(
            candidate_id,
            f"phase-1-treatment-{index}",
            outcome_score=result.score,
            evidence_ref=f"{evaluations_dir}/{treatment.evaluation_id}/{result.case_id}",
        )
    consolidated = pipeline.consolidate(
        candidate_id,
        approved_by="phase-1-governance",
        auto_consolidate=False,
    )

    followup_query = "¿Cómo recupero SQLite cuando aparece database locked?"
    before_followup = LearningRetriever(db_path=db_path).retrieve_decision(
        followup_query,
        run_id="phase-1-followup-before-stable-route",
        only_candidate_ids={candidate_id},
    )
    stable_retriever = LearningRetriever(
        db_path=db_path, allowed_states=frozenset({"consolidated"})
    )
    after_followup = stable_retriever.retrieve_decision(
        followup_query,
        run_id="phase-1-followup-after-consolidation",
        domain=CAPABILITY,
        only_candidate_ids={candidate_id},
    )
    audit_row_id = stable_retriever.persist_decision(after_followup)
    causal_use = stable_retriever.confirm_causal_use(
        after_followup, candidate_id, evaluator_confirmed=True
    )

    return {
        "schema_version": "1.0.0",
        "sha": sha,
        "capability": CAPABILITY,
        "benchmark": loaded.suite.to_dict(),
        "baseline": baseline.to_dict(),
        "treatment": treatment.to_dict(),
        "comparison": comparison.to_dict(),
        "regression_gate": regression.to_dict(),
        "candidate": {
            "candidate_id": candidate_id,
            "source_ref": candidate["source_ref"],
            "status": consolidated["status"],
            "semantic_document_id": consolidated["semantic_document_id"],
        },
        "followup": {
            "run_id": after_followup.run_id,
            "query": followup_query,
            "before_injected_ids": before_followup.injected_ids,
            "after_injected_ids": after_followup.injected_ids,
            "decision_changed": not before_followup.injected_ids
            and candidate_id in after_followup.injected_ids,
            "causal_use_confirmed": causal_use,
            "audit_row_id": audit_row_id,
        },
        "closure": {
            "baseline_lt_candidate": baseline.aggregate_score
            < treatment.aggregate_score,
            "held_out_not_worse": treatment.metadata["split_scores"]["held_out"]
            >= baseline.metadata["split_scores"]["held_out"],
            "regression_pass": regression.decision == "pass",
            "consolidated": consolidated["status"] == "consolidated",
            "recovered_later": candidate_id in after_followup.injected_ids,
            "later_use_improved": causal_use,
        },
    }

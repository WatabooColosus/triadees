from __future__ import annotations

import sqlite3

import pytest

from triade.neurons.competency_store import CompetencyStore
from triade.workers.state_store import WorkerStateStore


def prepared_session(tmp_path, *, candidate_id="candidate-source-a"):
    path = tmp_path / "education-evidence.db"
    WorkerStateStore(path)
    store = CompetencyStore(path)
    with store.connect() as conn:
        neuron_id = conn.execute(
            """INSERT INTO neurons(name,mission,domain,rules,triggers,inputs_allowed,outputs_allowed,
            forbidden_actions,success_metrics,evidence_required,activation_policy,contract_json,status,created_by)
            VALUES('Investigadora','contrastar fuentes','research','[]','[]','[]','[]','[]','[]','[]','{}','{}','experimental','test')"""
        ).lastrowid
    competency = store.ensure_competency(int(neuron_id), "research", "contrastar fuentes")
    curriculum = store.ensure_curriculum(int(neuron_id), None, "research", "contrastar fuentes")
    session = store.record_session(
        curriculum_id=curriculum["curriculum_id"], neuron_id=int(neuron_id),
        competency_id=competency["competency_id"], state="lesson_prepared",
        material_refs=["https://a.example/doc", "https://b.example/doc"], independent_sources=2,
        lesson={"truth_status": "candidate", "candidate_ids": [candidate_id]}, exercise={"type": "held_out"},
        evaluation={"passed": False}, result="uncertain",
    )
    return path, store, session["session_id"]


def test_education_cannot_self_approve(tmp_path):
    _, store, session_id = prepared_session(tmp_path)
    with pytest.raises(ValueError, match="independiente"):
        store.record_independent_evaluation(
            session_id, evaluator_id="education_cycle", baseline_score=.4, post_score=.8,
            evidence_ref="evaluation:1",
        )


def test_learning_requires_independent_improvement_and_three_unique_runs(tmp_path):
    path, store, session_id = prepared_session(tmp_path)
    evaluated = store.record_independent_evaluation(
        session_id, evaluator_id="critical_evaluator:v1", baseline_score=.4, post_score=.8,
        evidence_ref="evaluation:held-out-1",
    )
    assert evaluated["state"] == "evaluated_candidate"
    assert evaluated["learned"] is False
    first = store.record_run_application(
        session_id, run_id="run-1", outcome_score=.8, evidence_ref="run-evaluation:1"
    )
    duplicate = store.record_run_application(
        session_id, run_id="run-1", outcome_score=1.0, evidence_ref="run-evaluation:duplicate"
    )
    assert first["learned"] is False
    assert duplicate["duplicate"] is True
    assert duplicate["applied_run_count"] == 1
    store.record_run_application(session_id, run_id="run-2", outcome_score=.75, evidence_ref="run-evaluation:2")
    final = store.record_run_application(session_id, run_id="run-3", outcome_score=.9, evidence_ref="run-evaluation:3")
    assert final["learned"] is True
    assert final["state"] == "validated_in_runs"
    with sqlite3.connect(path) as conn:
        status = conn.execute("SELECT status FROM neuron_competencies").fetchone()[0]
    assert status == "validated_in_runs"


def test_failed_evaluation_cannot_be_applied(tmp_path):
    _, store, session_id = prepared_session(tmp_path)
    rejected = store.record_independent_evaluation(
        session_id, evaluator_id="critical_evaluator:v1", baseline_score=.7, post_score=.71,
        evidence_ref="evaluation:no-improvement",
    )
    assert rejected["state"] == "evaluation_rejected"
    with pytest.raises(ValueError, match="no superó"):
        store.record_run_application(
            session_id, run_id="run-1", outcome_score=.9, evidence_ref="run-evaluation:1"
        )


def test_candidate_application_connects_only_matching_evaluated_session(tmp_path):
    _, store, session_id = prepared_session(tmp_path, candidate_id="candidate-real")
    store.record_independent_evaluation(
        session_id, evaluator_id="critical_evaluator:v1", baseline_score=.4, post_score=.8,
        evidence_ref="evaluation:held-out",
    )
    assert store.record_candidate_application(
        "candidate-other", run_id="run-1", outcome_score=.8, evidence_ref="run-evaluation:1"
    ) == []
    applied = store.record_candidate_application(
        "candidate-real", run_id="run-1", outcome_score=.8, evidence_ref="run-evaluation:1"
    )
    assert len(applied) == 1
    assert applied[0]["applied_run_count"] == 1

"""El worker autónomo A/B usa observaciones reales y falla cerrado."""
import json
import sqlite3

from triade.self_improvement.worker_failure_ab import WorkerFailureABRunner
from triade.workers.mission_planner import MissionPlanner


def _database(tmp_path):
    db = tmp_path / "failure-ab.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE worker_tasks (
                id INTEGER PRIMARY KEY, task_type TEXT NOT NULL,
                status TEXT NOT NULL, result_json TEXT, run_ref TEXT
            );
            CREATE TABLE worker_events (
                id INTEGER PRIMARY KEY, task_id INTEGER, task_type TEXT,
                run_ref TEXT, event_type TEXT, payload_json TEXT
            );
            CREATE TABLE regression_reports (
                report_id TEXT PRIMARY KEY, capability TEXT,
                decision TEXT, findings_json TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO regression_reports VALUES(?,?,?,?)",
            (
                "real-report",
                "worker_failure",
                "fail",
                json.dumps(
                    [
                        {
                            "metric_id": "worker_outcome_classification",
                            "status": "fail",
                            "baseline_score": 1.0,
                            "candidate_score": 0.60,
                        }
                    ]
                ),
            ),
        )
    return db


def _event(db, task_id, status, payload):
    task_type = "pulse_check"
    run_ref = f"worker-run-{task_id}"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO worker_tasks VALUES (?,?,?,?,?)",
            (task_id, task_type, status, json.dumps(payload), run_ref),
        )
        conn.execute(
            "INSERT INTO worker_events VALUES (?,?,?,?,?,?)",
            (
                task_id, task_id, task_type, run_ref, f"task_{status}",
                json.dumps(payload),
            ),
        )


def _fill_independent_cohort(db):
    for task_id, status in enumerate(
        ("failed", "timeout", "blocked", "lease_lost", "dead_letter", "failed"),
        start=1,
    ):
        _event(db, task_id, status, {"error": "verified_worker_error"})
    _event(db, 11, "failed", {"reason": "cancellation_requested"})
    _event(db, 12, "failed", {"reason": "cancellation_requested"})
    _event(db, 13, "failed", {"reason": "cancellation_requested"})
    _event(db, 14, "completed", {"status": "completed"})
    _event(db, 15, "observed", {"status": "observed"})


def test_autonomous_ab_evaluates_multiple_versions_without_promotion(tmp_path):
    db = _database(tmp_path)
    _fill_independent_cohort(db)
    planner = MissionPlanner(db)
    scheduled = planner._plan_failure_ab_evaluation()
    assert len(scheduled) == 1
    assert scheduled[0].task_type == "failure_ab_evaluation"
    assert scheduled[0].payload["regression_report_id"] == "real-report"
    result = WorkerFailureABRunner(db).evaluate(
        "real-report", "worker_outcome_classification"
    )
    assert result["ab_verdict"] == "eligible_for_governed_review"
    assert result["winner"] == "B1-explicit-cancellation"
    assert result["holdout_executed"] is True
    assert result["critical_controls_passed"] is True
    assert result["activated"] is False
    assert result["stable_memory_written"] is False
    assert planner._plan_failure_ab_evaluation() == []


def test_no_evidence_without_multiple_independent_events(tmp_path):
    db = _database(tmp_path)
    _event(db, 1, "failed", {"error": "only_one_failure"})
    result = WorkerFailureABRunner(db).evaluate(
        "real-report", "worker_outcome_classification"
    )
    assert result["status"] == "no_evidence"
    assert result["reason"] == "insufficient_distinct_worker_outcomes"
    assert MissionPlanner(db)._plan_failure_ab_evaluation() == []


def test_mismatched_event_and_task_are_never_learning_evidence(tmp_path):
    db = _database(tmp_path)
    _fill_independent_cohort(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE worker_events SET run_ref='other-run' WHERE task_id=11"
        )
    assert not any(
        case.case_id == "task-11"
        for case in WorkerFailureABRunner(db).replay_cases()
    )


def test_no_false_worker_regression_on_unrelated_metric(tmp_path):
    db = _database(tmp_path)
    _fill_independent_cohort(db)
    result = WorkerFailureABRunner(db).evaluate(
        "real-report", "unsupported_metric"
    )
    assert result["status"] == "no_evidence"
    assert result["stable_memory_written"] is False

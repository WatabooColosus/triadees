"""El worker autónomo A/B usa observaciones reales y falla cerrado."""
import hashlib
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


def _add_v2_outcome(db, tmp_path, task_id, status, payload):
    artifact_dir = tmp_path / "runs" / f"task-{task_id}"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    result_path = artifact_dir / "result.json"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    result_path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    manifest = {
        "task_id": str(task_id),
        "task_type": "pulse_check",
        "worker_id": "worker-1",
        "status": status,
        "lease_generation": 1,
        "result_hash": digest,
        "artifact_hashes": {"result.json": digest},
    }
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest))
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO autonomous_tasks VALUES(?,?,?,?,?,?,?)",
            (
                str(task_id), "pulse_check", status,
                "worker-1", str(result_path), 1, "{}",
            ),
        )
        conn.execute(
            "INSERT INTO autonomous_task_transitions "
            "(task_id,to_status,result_ref,worker_id,lease_generation) "
            "VALUES(?,?,?,?,?)",
            (str(task_id), status, str(result_path), "worker-1", 1),
        )
    return result_path


def test_v2_receipts_provide_real_cases_without_legacy_events(tmp_path):
    db = _database(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE autonomous_tasks (
                task_id TEXT, task_type TEXT, status TEXT, worker_id TEXT,
                result_ref TEXT, lease_generation INTEGER, payload_json TEXT
            );
            CREATE TABLE autonomous_task_transitions (
                transition_id INTEGER PRIMARY KEY, task_id TEXT,
                to_status TEXT, result_ref TEXT, worker_id TEXT,
                lease_generation INTEGER
            );
            """
        )
    for task_id, status in enumerate(
        ("failed", "timeout", "blocked", "lease_lost", "dead_letter", "failed"),
        start=100,
    ):
        _add_v2_outcome(
            db, tmp_path, task_id, status, {"error": "verified_failure"}
        )
    for task_id in (200, 201, 202):
        _add_v2_outcome(
            db, tmp_path, task_id, "failed",
            {"reason": "cancellation_requested"},
        )
    _add_v2_outcome(db, tmp_path, 203, "completed", {"status": "completed"})
    tamper = _add_v2_outcome(
        db, tmp_path, 204, "observed", {"status": "observed"}
    )
    tamper.write_text('{"status":"failed"}', encoding="utf-8")
    assert WorkerFailureABRunner(db).replay_cases() == []
    _add_v2_outcome(db, tmp_path, 205, "observed", {"status": "observed"})
    cases = WorkerFailureABRunner(db).replay_cases()
    assert len(cases) == 11
    assert all(x.evidence_ref.startswith("autonomous-transition:") for x in cases)
    assert MissionPlanner(db)._plan_failure_ab_evaluation()
    outcome = WorkerFailureABRunner(db).evaluate(
        "real-report", "worker_outcome_classification"
    )
    assert outcome["winner"] == "B1-explicit-cancellation"
    assert outcome["stable_memory_written"] is False

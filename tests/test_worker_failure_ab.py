"""El worker autónomo A/B usa observaciones reales y falla cerrado."""

import hashlib
import json
import sqlite3

from triade.self_improvement.worker_failure_ab import WorkerFailureABRunner
from triade.self_improvement.worker_failure_canary import WorkerFailureShadowCanary
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
            "INSERT INTO worker_events "
            "(id,task_id,task_type,run_ref,event_type,payload_json) "
            "VALUES (?,?,?,?,?,?)",
            (
                task_id,
                task_id,
                task_type,
                run_ref,
                f"task_{status}",
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
    assert scheduled[0].payload == {"mode": "auto_measure"}
    result = WorkerFailureABRunner(db).evaluate(
        "real-report", "worker_outcome_classification"
    )
    assert result["ab_verdict"] == "eligible_for_governed_review"
    assert result["winner"] == "B1-explicit-cancellation"
    assert result["holdout_executed"] is True
    assert result["critical_controls_passed"] is True
    assert result["activated"] is False
    assert result["stable_memory_written"] is False
    # El A/B ya consumido no se repite: la reparación funcional es un
    # protocolo distinto y solo se programa con evidencia verificable.
    followup = planner._plan_failure_ab_evaluation()
    assert len(followup) == 1
    assert followup[0].task_type == "failure_ab_evaluation"
    assert followup[0].source == "verified_worker_failure"
    assert followup[0].payload == {
        "mode": "functional_repair",
        "evidence_ref": "worker-event:13",
    }


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
        conn.execute("UPDATE worker_events SET run_ref='other-run' WHERE task_id=11")
    assert not any(
        case.case_id == "task-11" for case in WorkerFailureABRunner(db).replay_cases()
    )


def test_no_false_worker_regression_on_unrelated_metric(tmp_path):
    db = _database(tmp_path)
    _fill_independent_cohort(db)
    result = WorkerFailureABRunner(db).evaluate("real-report", "unsupported_metric")
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
                str(task_id),
                "pulse_check",
                status,
                "worker-1",
                str(result_path),
                1,
                "{}",
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
        _add_v2_outcome(db, tmp_path, task_id, status, {"error": "verified_failure"})
    for task_id in (200, 201, 202):
        _add_v2_outcome(
            db,
            tmp_path,
            task_id,
            "failed",
            {"reason": "cancellation_requested"},
        )
    _add_v2_outcome(db, tmp_path, 203, "completed", {"status": "completed"})
    tamper = _add_v2_outcome(db, tmp_path, 204, "observed", {"status": "observed"})
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


def test_real_worker_outcomes_autonomously_generate_formal_regression(tmp_path):
    db = _database(tmp_path)
    _fill_independent_cohort(db)
    with sqlite3.connect(db) as conn:
        for column in (
            "candidate_id",
            "suite_id",
            "suite_version",
            "baseline_evaluation_id",
            "candidate_evaluation_id",
            "metadata_json",
            "created_at",
        ):
            conn.execute(f"ALTER TABLE regression_reports ADD COLUMN {column} TEXT")
    runner = WorkerFailureABRunner(db)
    assert runner.pending_auto_measurement() is True
    plan = MissionPlanner(db)._plan_failure_ab_evaluation()
    assert len(plan) == 1
    assert plan[0].payload == {"mode": "auto_measure"}
    result = runner.evaluate_auto()
    assert result["ab_verdict"] == "eligible_for_governed_review"
    assert result["stable_memory_written"] is False
    assert result["activated"] is False
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT decision,metadata_json FROM regression_reports "
            "WHERE suite_id='worker-outcome-classification'"
        ).fetchone()
    assert row is not None
    assert row[0] == "fail"
    assert len(json.loads(row[1])["case_refs"]) == 11
    # No se repite la medición; solo puede continuar la reparación gobernada.
    followup = MissionPlanner(db)._plan_failure_ab_evaluation()
    assert len(followup) == 1
    assert followup[0].source == "verified_worker_failure"
    assert followup[0].payload == {
        "mode": "functional_repair",
        "evidence_ref": "worker-event:13",
    }


def test_auto_measurement_refuses_cohort_without_measured_gap(tmp_path):
    db = _database(tmp_path)
    _fill_independent_cohort(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE worker_tasks SET status='completed', "
            "result_json='{}' WHERE id IN (11,12,13)"
        )
        conn.execute(
            "UPDATE worker_events SET event_type='task_completed', "
            "payload_json='{}' WHERE task_id IN (11,12,13)"
        )
    assert WorkerFailureABRunner(db).pending_auto_measurement() is False


def test_canary_uses_only_events_after_offline_experiment(tmp_path):
    db = _database(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("ALTER TABLE worker_events ADD COLUMN created_at TEXT")
    _fill_independent_cohort(db)
    baseline = WorkerFailureABRunner(db).evaluate(
        "real-report", "worker_outcome_classification"
    )
    assert baseline["eligible_for_canary"] is True
    canary = WorkerFailureShadowCanary(db)
    assert canary.ready() is False
    assert canary.observe()["status"] == "no_evidence"
    for task_id, status, payload in (
        (301, "failed", {"error": "verified_fault"}),
        (302, "blocked", {"error": "verified_fault"}),
        (303, "timeout", {"error": "verified_fault"}),
        (304, "failed", {"reason": "cancellation_requested"}),
        (305, "completed", {"status": "completed"}),
    ):
        _event(db, task_id, status, payload)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE worker_events SET created_at='2099-04-04T14:00:00+00:00' "
            "WHERE task_id >= 301"
        )
    assert canary.ready() is True
    plan = MissionPlanner(db)._plan_failure_ab_evaluation()
    assert len(plan) == 1
    assert plan[0].payload == {"mode": "shadow_canary"}
    result = canary.observe()
    assert result["shadow_verdict"] == "supported"
    assert result["evaluated_cases"] == 5
    assert result["operational_causality_proven"] is False
    assert result["production_effect_applied"] is False
    assert result["stable_memory_written"] is False
    assert canary.ready() is False
    # La cohorte del canary queda consumida; una reparación requiere su propio gate.
    followup = MissionPlanner(db)._plan_failure_ab_evaluation()
    assert len(followup) == 1
    assert followup[0].source == "verified_worker_failure"
    assert followup[0].payload.get("mode") == "functional_repair"
    assert followup[0].payload.get("evidence_ref") in {
        "worker-event:11",
        "worker-event:12",
        "worker-event:13",
        "worker-event:304",
    }


def test_shadow_canary_cannot_reuse_training_cases(tmp_path):
    db = _database(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("ALTER TABLE worker_events ADD COLUMN created_at TEXT")
    _fill_independent_cohort(db)
    WorkerFailureABRunner(db).evaluate("real-report", "worker_outcome_classification")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE worker_events SET created_at='2099-04-04T14:00:00+00:00'")
    canary = WorkerFailureShadowCanary(db)
    assert canary.ready() is False
    assert canary.observe()["status"] == "no_evidence"


def test_v2_relative_receipts_require_authorized_root(tmp_path, monkeypatch):
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
    path = _add_v2_outcome(
        db, tmp_path, 950, "failed", {"error": "genuine_worker_failure"}
    )
    relative = path.relative_to(tmp_path).as_posix()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE autonomous_tasks SET result_ref=? WHERE task_id='950'",
            (relative,),
        )
        conn.execute(
            "UPDATE autonomous_task_transitions SET result_ref=? "
            "WHERE task_id='950'",
            (relative,),
        )
    unrelated = tmp_path / "different_cwd"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    assert WorkerFailureABRunner(db)._load_observations() == []
    loaded = WorkerFailureABRunner(
        db, artifact_root=tmp_path
    )._load_observations()
    assert len(loaded) == 1
    assert loaded[0]["status"] == "failed"
    # Reject traversal, even if a path outside the authorized root exists.
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE autonomous_tasks SET result_ref=? WHERE task_id='950'",
            ("../runs/task-950/result.json",),
        )
        conn.execute(
            "UPDATE autonomous_task_transitions SET result_ref=? "
            "WHERE task_id='950'",
            ("../runs/task-950/result.json",),
        )
    assert WorkerFailureABRunner(
        db, artifact_root=tmp_path
    )._load_observations() == []


def test_v2_relative_receipts_reject_symlink_outside_root(tmp_path):
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
    outside = tmp_path / "outside"
    outside.mkdir()
    _add_v2_outcome(db, outside, 951, "failed", {"error": "real"})
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(outside / "runs", target_is_directory=True)
    reference = "link/task-951/result.json"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE autonomous_tasks SET result_ref=? WHERE task_id='951'",
            (reference,),
        )
        conn.execute(
            "UPDATE autonomous_task_transitions SET result_ref=? "
            "WHERE task_id='951'",
            (reference,),
        )
    assert WorkerFailureABRunner(db, artifact_root=root)._load_observations() == []

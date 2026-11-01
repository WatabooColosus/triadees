"""Fallo verificable -> variantes deterministas -> gate funcional, sin promoción."""
import sqlite3
import subprocess
from pathlib import Path

import pytest

from triade.evolution.autonomous_worker_repair import (
    AutonomousWorkerRepair,
    _is_repairable_incident,
)
from triade.workers.mission_planner import MissionPlanner


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "incidents.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE worker_tasks(
                id INTEGER PRIMARY KEY,task_type TEXT,status TEXT,
                result_json TEXT,run_ref TEXT
            );
            CREATE TABLE worker_events(
                id INTEGER PRIMARY KEY,task_id INTEGER,task_type TEXT,
                run_ref TEXT,event_type TEXT,payload_json TEXT
            );
            """
        )
    repo = tmp_path / "repo"
    target = repo / "triade" / "workers" / "worker_loop.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "def is_failure(status):\n"
        '    if status == "cancelled":\n'
        "        return False\n"
        "    return True\n",
        encoding="utf-8",
    )
    test_path = repo / "tests" / "test_failures_become_knowledge.py"
    test_path.parent.mkdir()
    test_path.write_text(
        "def test_regression():\n    assert True\n",
        encoding="utf-8",
    )
    return db_path, repo


def _record(db_path, n, status="failed", reason="cancellation_requested",
            *, mismatched=False):
    import json

    run_ref = f"run-{n}"
    payload = {"reason": reason}
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO worker_tasks VALUES (?,?,?,?,?)",
            (n, "pulse_check", status, json.dumps(payload), run_ref),
        )
        conn.execute(
            "INSERT INTO worker_events VALUES (?,?,?,?,?,?)",
            (
                n, n, "pulse_check",
                "fake-run" if mismatched else run_ref,
                f"task_{status}", json.dumps(payload),
            ),
        )
    return f"worker-event:{n}"


def test_real_matching_failed_incident_is_selected_not_prompt(tmp_path):
    db, repo = _fixture(tmp_path)
    _record(db, 1, status="cancelled")
    _record(db, 2, status="failed", reason="sql_error")
    event = _record(db, 3, status="failed")
    engine = AutonomousWorkerRepair(db, repo)
    assert engine.pending_incident() == event
    assert not _is_repairable_incident(
        {"status": "cancelled", "payload": {"reason": "cancellation_requested"}}
    )


def test_forged_or_uncorrelated_event_is_rejected(tmp_path):
    db, repo = _fixture(tmp_path)
    _record(db, 1, mismatched=True)
    assert AutonomousWorkerRepair(db, repo).pending_incident() is None
    assert AutonomousWorkerRepair(db, repo).evaluate("worker-event:1") == {
        "status": "no_evidence",
        "evidence_ref": "worker-event:1",
        "protocol": "worker-repair-v1",
        "rule_id": "requested_cancellation_marked_failed",
        "production_changed": False,
        "stable_memory_written": False,
        "approval_requested_from_user": False,
        "reason": "unverified_or_inapplicable_incident",
    }


def test_b1_b2_patches_apply_without_touching_source_or_test(tmp_path):
    db, repo = _fixture(tmp_path)
    repair = AutonomousWorkerRepair(db, repo)
    source_file = repo / "triade" / "workers" / "worker_loop.py"
    oracle = repo / "tests" / "test_failures_become_knowledge.py"
    before = source_file.read_bytes()
    oracle_before = oracle.read_bytes()
    variants = repair._build_variants()
    assert len(variants) == 2
    assert variants[0][0] != variants[1][0]
    assert variants[0][1] != variants[1][1]
    for _, patch in variants:
        patch_file = tmp_path / "candidate.patch"
        patch_file.write_text(patch, encoding="utf-8")
        subprocess.run(
            ["git", "apply", "--check", str(patch_file)],
            cwd=repo,
            check=True,
            capture_output=True,
        )
    assert source_file.read_bytes() == before
    assert oracle.read_bytes() == oracle_before


def test_autonomous_repair_is_bounded_idempotent_and_never_deploys(tmp_path):
    db, repo = _fixture(tmp_path)
    observed = _record(db, 1)
    calls = []

    class StubEngine:
        def __init__(self, *, repo, db_path):
            assert db_path == db

        def _require_trusted_regression_test(self, filename):
            assert filename == "tests/test_failures_become_knowledge.py"

        def _git(self, args, worktree):
            assert args == ["rev-parse", "HEAD"]
            return "e" * 40

        def propose(self, **kwargs):
            calls.append(kwargs)
            return {
                "status": "rejected",
                "evolution_id": f"evo-{len(calls)}",
                "review": {
                    "measured_functional_repair": False,
                    "rollback_verified": False,
                },
            }

    repair = AutonomousWorkerRepair(db, repo, engine_factory=StubEngine)
    assert repair.pending_incident() == observed
    result = repair.evaluate(observed)
    assert result["status"] == "no_certified_repair"
    assert result["production_changed"] is False
    assert result["stable_memory_written"] is False
    assert len(result["variants"]) == 2
    assert len(calls) == 2
    assert all(c["budget"].max_gpu_minutes == 0 for c in calls)
    assert all(c["budget"].max_files == 1 for c in calls)
    assert all(c["regression_test"].startswith("tests/test_") for c in calls)
    assert repair.pending_incident() is None
    again = repair.evaluate(observed)
    assert again["reason"] == "already_evaluated_or_budget_exhausted"
    assert len(calls) == 2
    _record(db, 2)
    second = repair.evaluate("worker-event:2")
    assert second["status"] == "no_certified_repair"
    _record(db, 3)
    assert repair.pending_incident() is None


def test_missing_oracle_or_ambiguous_recipe_fails_closed(tmp_path):
    db, repo = _fixture(tmp_path)
    event = _record(db, 1)
    repair = AutonomousWorkerRepair(db, repo)
    (repo / "tests" / "test_failures_become_knowledge.py").unlink()
    assert repair.pending_incident() is None
    (repo / "triade" / "workers" / "worker_loop.py").write_text(
        "def foo(): return 1\n", encoding="utf-8"
    )
    assert repair.pending_incident() is None
    with pytest.raises(ValueError, match="repair_source_guard_missing_or_ambiguous"):
        repair._build_variants()
    assert repair.evaluate(event)["status"] == "no_evidence"


def test_worker_planner_can_schedule_real_repair_without_user_prompt(tmp_path):
    db, repo = _fixture(tmp_path)
    _record(db, 1)
    # La planificación usa el checkout real, por diseño; la base de eventos
    # es independiente y solo ofrece evidencia verificada.
    plan = MissionPlanner(db)._plan_failure_ab_evaluation()
    assert any(
        task.payload.get("mode") == "functional_repair"
        and task.payload.get("evidence_ref") == "worker-event:1"
        for task in plan
    )

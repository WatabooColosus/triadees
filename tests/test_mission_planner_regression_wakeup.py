"""The mission planner must awaken real regression harvest even without candidates."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from triade.self_improvement.failure_learning import FailureLearningLoop
from triade.workers.mission_planner import MissionPlanner
from triade.workers.state_store import WorkerStateStore


def failed_report(db: Path, report_id: str, findings: list[dict]) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS regression_reports (
                report_id TEXT, candidate_id TEXT, capability TEXT,
                decision TEXT, findings_json TEXT
            )"""
        )
        conn.execute(
            "INSERT INTO regression_reports VALUES (?,?,?,?,?)",
            (report_id, "candidate-1", "triade_vitality", "fail", json.dumps(findings)),
        )


def test_real_regression_wakes_harvest_without_learning_queue(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    WorkerStateStore(db)
    failed_report(
        db,
        "measured-report",
        [
            {
                "status": "fail",
                "metric_id": "coherence",
                "severity": "high",
                "baseline_score": 0.92,
                "candidate_score": 0.75,
                "absolute_delta": -0.17,
                "reason": "regression",
            }
        ],
    )
    planner = MissionPlanner(db)
    work = planner._plan_unharvested_regressions()
    assert len(work) == 1
    assert work[0].source == "measured_regression_backlog"
    assert work[0].payload["regression_report_id"] == "measured-report"
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM learning_queue").fetchone()[0] == 0
    harvested = FailureLearningLoop(db).harvest()
    assert harvested["lessons_recorded"] == 1
    assert planner._plan_unharvested_regressions() == []


def test_no_failing_metric_does_not_create_busy_loop(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    WorkerStateStore(db)
    failed_report(
        db,
        "not-an-actionable-failure",
        [{"status": "pass", "metric_id": "coherence"}],
    )
    assert MissionPlanner(db)._plan_unharvested_regressions() == []


def test_empty_database_without_regressions_remains_idle(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    WorkerStateStore(db)
    assert MissionPlanner(db)._plan_unharvested_regressions() == []


def test_malformed_findings_do_not_crash_or_trigger_harvest(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    WorkerStateStore(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            """CREATE TABLE regression_reports (
                report_id TEXT, candidate_id TEXT, capability TEXT,
                decision TEXT, findings_json TEXT
            )"""
        )
        conn.executemany(
            "INSERT INTO regression_reports VALUES (?,?,?,?,?)",
            [
                ("malformed", "c1", "triade_vitality", "fail", "{broken"),
                ("scalar", "c2", "triade_vitality", "fail", '["not-an-object"]'),
            ],
        )
    assert MissionPlanner(db)._plan_unharvested_regressions() == []

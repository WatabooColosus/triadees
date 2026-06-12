"""Tests del MissionPlanner."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from triade.workers.mission_planner import MissionPlanner, PlannedTask
from triade.core.neuron_missions import NeuronMission, NeuronMissionStore


def make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
    return db_path


def test_planned_task_to_dict() -> None:
    task = PlannedTask(
        task_type="pending_learning_review",
        priority=20,
        reason="Test reason",
        source="test",
        related_neuron_id=5,
        related_candidate_id=10,
        payload={"key": "value"},
    )
    d = task.to_dict()
    assert d["task_type"] == "pending_learning_review"
    assert d["priority"] == 20
    assert d["reason"] == "Test reason"
    assert d["related_neuron_id"] == 5
    assert d["related_candidate_id"] == 10
    assert d["payload"]["key"] == "value"


def test_plan_empty_db_returns_minimal_tasks(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    planner = MissionPlanner(db_path=db_path)
    tasks = planner.plan_cycle()
    assert isinstance(tasks, list)
    assert all(isinstance(t, PlannedTask) for t in tasks)


def test_plan_pending_learning(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO learning_queue
            (candidate_id, title, content, source_type, risk_level, confidence, status, domain, source_ref, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("cand-001", "Test candidate", "content here", "conversation", "low", 0.8, "candidate", "test", "run:001", "2026-01-01"),
        )
    planner = MissionPlanner(db_path=db_path)
    tasks = planner.plan_cycle()
    learning_tasks = [t for t in tasks if t.task_type == "pending_learning_review"]
    assert len(learning_tasks) >= 1
    reasons = [t.reason for t in learning_tasks]
    assert any("Test candidate" in r for r in reasons)


def test_plan_priority_ordering(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        for i in range(3):
            conn.execute(
                """INSERT INTO learning_queue
                (candidate_id, title, content, source_type, risk_level, confidence, status, domain, source_ref, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (f"cand-{i:03d}", f"Cand {i}", "content", "conversation", "low", 0.9 - i * 0.1, "candidate", "test", "run:001", "2026-01-01"),
            )
    planner = MissionPlanner(db_path=db_path)
    tasks = planner.plan_cycle()
    priorities = [t.priority for t in tasks]
    assert priorities == sorted(priorities)


def test_plan_active_missions(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)
    store.create_mission(NeuronMission(
        neuron_id=1,
        title="Active mission",
        mission="Test",
        domain="test",
        status="experimental",
    ))
    planner = MissionPlanner(db_path=db_path)
    tasks = planner.plan_cycle()
    mission_tasks = [t for t in tasks if t.task_type == "experimental_neuron_activity"]
    assert len(mission_tasks) >= 1
    assert mission_tasks[0].related_neuron_id == 1


def test_plan_system_debt(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        for i in range(10):
            conn.execute(
                "INSERT INTO runs (run_id, source, user_input, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (f"run-{i:03d}", "test", "input", "ok", "2026-01-01"),
            )
    planner = MissionPlanner(db_path=db_path)
    tasks = planner.plan_cycle()
    debt_tasks = [t for t in tasks if t.task_type == "system_debt_scan"]
    assert len(debt_tasks) >= 1


def test_plan_respects_limit(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        for i in range(20):
            conn.execute(
                """INSERT INTO learning_queue
                (candidate_id, title, content, source_type, risk_level, confidence, status, domain, source_ref, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (f"cand-limit-{i:03d}", f"Cand {i}", "content", "conversation", "low", 0.5, "candidate", "test", "run:001", "2026-01-01"),
            )
    planner = MissionPlanner(db_path=db_path)
    tasks = planner.plan_cycle()
    assert len(tasks) <= 15

"""Tests del WorkerScheduler con MissionPlanner."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from triade.workers.scheduler import WorkerScheduler
from triade.workers.contracts import WorkerRunConfig
from triade.core.neuron_missions import NeuronMission, NeuronMissionStore


def make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
    migration = Path("triade/memory/migrations/003_living_workers.sql")
    if migration.exists():
        with sqlite3.connect(db_path) as conn:
            conn.executescript(migration.read_text(encoding="utf-8"))
    return db_path


def test_scheduler_returns_task_dicts(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    scheduler = WorkerScheduler(db_path=db_path)
    config = WorkerRunConfig()
    tasks = scheduler.schedule_cycle(run_ref="test-run-001", config=config)
    assert isinstance(tasks, list)
    assert len(tasks) > 0
    assert all("task_type" in t for t in tasks)
    assert all("priority" in t for t in tasks)


def test_scheduler_tasks_have_reason(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    scheduler = WorkerScheduler(db_path=db_path)
    config = WorkerRunConfig()
    tasks = scheduler.schedule_cycle(run_ref="test-run-002", config=config)
    for t in tasks:
        payload = t.get("payload", {})
        assert "reason" in payload or "scheduled" in payload


def test_scheduler_includes_planner_metadata(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO learning_queue
            (candidate_id, title, content, source_type, risk_level, confidence, status, domain, source_ref, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("cand-test-001", "Test", "content", "conversation", "low", 0.8, "candidate", "test", "run:001", "2026-01-01"),
        )
    scheduler = WorkerScheduler(db_path=db_path)
    config = WorkerRunConfig()
    tasks = scheduler.schedule_cycle(run_ref="test-run-003", config=config)
    learning_tasks = [t for t in tasks if t.get("task_type") == "pending_learning_review"]
    if learning_tasks:
        payload = learning_tasks[0].get("payload", {})
        assert "reason" in payload
        assert "source" in payload


def test_scheduler_with_active_missions(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)
    store.create_mission(NeuronMission(
        neuron_id=1,
        title="Active",
        mission="Test",
        status="experimental",
    ))
    scheduler = WorkerScheduler(db_path=db_path)
    config = WorkerRunConfig()
    tasks = scheduler.schedule_cycle(run_ref="test-run-004", config=config)
    mission_tasks = [t for t in tasks if t.get("task_type") == "experimental_neuron_activity"]
    assert len(mission_tasks) >= 1


def test_scheduler_task_types_unchanged() -> None:
    scheduler = WorkerScheduler(db_path=":memory:")
    types = scheduler.task_types()
    assert len(types) == 11
    assert "pulse_check" in types
    assert "neuron_candidate_formation" in types

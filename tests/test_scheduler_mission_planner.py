"""Tests del WorkerScheduler con MissionPlanner."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.core.neuron_missions import (
    NeuronEvidence,
    NeuronMission,
    NeuronMissionStore,
)
from triade.workers.contracts import WORKER_TASK_TYPES, WorkerRunConfig
from triade.workers.mission_planner import MissionPlanner, PlannedTask
from triade.workers.scheduler import WorkerScheduler


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
            (
                "cand-test-001",
                "Test",
                "content",
                "conversation",
                "low",
                0.8,
                "candidate",
                "test",
                "run:001",
                "2026-01-01",
            ),
        )
    scheduler = WorkerScheduler(db_path=db_path)
    config = WorkerRunConfig()
    tasks = scheduler.schedule_cycle(run_ref="test-run-003", config=config)
    learning_tasks = [
        t for t in tasks if t.get("task_type") == "pending_learning_review"
    ]
    if learning_tasks:
        payload = learning_tasks[0].get("payload", {})
        assert "reason" in payload
        assert "source" in payload


def test_event_driven_learning_is_not_dropped_by_type_cooldown(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    scheduler = WorkerScheduler(db_path=db_path)
    scheduler.adaptive.record_task_execution(
        "neural_learning_distribution", 1.0, True, run_ref="previous-event"
    )
    planned = PlannedTask(
        task_type="neural_learning_distribution",
        priority=10,
        reason="different candidate",
        source="test",
        payload={"candidate_id": "candidate-2"},
    )
    tasks = scheduler._enqueue_planned([planned], run_ref="new-event")
    assert [task["task_type"] for task in tasks] == ["neural_learning_distribution"]


def test_scheduler_with_active_missions(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)
    mission_id = store.create_mission(
        NeuronMission(
            neuron_id=1,
            title="Active",
            mission="Test",
            status="experimental",
        )
    )
    store.record_evidence(
        NeuronEvidence(
            mission_id=mission_id,
            neuron_id=1,
            evidence_type="user_run",
            source="user_run",
            content="Resultado externo reproducible",
            refs=["run:user-1"],
            score=0.8,
        )
    )
    scheduler = WorkerScheduler(db_path=db_path)
    config = WorkerRunConfig()
    tasks = scheduler.schedule_cycle(run_ref="test-run-004", config=config)
    mission_tasks = [
        t for t in tasks if t.get("task_type") == "experimental_neuron_activity"
    ]
    assert len(mission_tasks) >= 1


def test_scheduler_rejects_self_referential_mission_evidence(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)
    mission_id = store.create_mission(
        NeuronMission(
            neuron_id=1,
            title="No self feed",
            mission="Test",
            status="experimental",
        )
    )
    store.record_evidence(
        NeuronEvidence(
            mission_id=mission_id,
            neuron_id=1,
            evidence_type="mission_cycle",
            source="worker",
            content="Autorreferencia",
            refs=["worker:self"],
            score=0.9,
        )
    )

    tasks = WorkerScheduler(db_path=db_path).schedule_cycle(
        "test-no-self", WorkerRunConfig()
    )
    assert not any(
        task["task_type"] == "experimental_neuron_activity" for task in tasks
    )


def test_planner_deduplicates_task_types_without_distinct_targets(
    tmp_path: Path,
) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)
    store.create_mission(
        NeuronMission(
            neuron_id=1,
            title="Gap A",
            mission="Research A",
            status="experimental",
        )
    )
    store.create_mission(
        NeuronMission(
            neuron_id=2,
            title="Gap B",
            mission="Research B",
            status="experimental",
        )
    )

    planned = MissionPlanner(db_path=db_path).plan_cycle("dedup")
    generic = [task.task_type for task in planned if task.related_neuron_id is None]
    assert len(generic) == len(set(generic))


def test_scheduler_task_types_include_governed_education() -> None:
    scheduler = WorkerScheduler(db_path=":memory:")
    types = scheduler.task_types()
    # Se comprueba contra la fuente de verdad y no contra un número escrito a
    # mano: añadir un tipo no debe romper este test, pero olvidarse de
    # registrarlo en el scheduler sí.
    assert set(types) == set(WORKER_TASK_TYPES)
    assert "pulse_check" in types
    assert "neuron_candidate_formation" in types
    assert "research_curriculum" in types
    assert "encrypted_backup" in types
    assert "neuron_education_cycle" in types
    assert "write_governed_text_artifact" in types
    assert "self_improvement_evaluation" in types
    # El canary se observa en ciclos posteriores, no dentro de la evaluación.
    assert "self_improvement_canary_observation" in types
    # El aprendizaje productivo: extraer, deduplicar y medir.
    assert "learning_candidate_generation" in types
    assert "learning_candidate_deduplication" in types
    assert "learning_evidence_generation" in types

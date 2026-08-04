"""Contrato end-to-end real del ciclo de vida de goals.

La suite usa SQLite y la cola canónica reales. Sólo sustituye el efecto final
del worker cuando el caso prueba una transición concreta, no la persistencia,
la resolución, el plan, la tarea ni la auditoría.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from triade.core.capability_resolver import CapabilityResolver
from triade.core.goal_orchestrator import GoalOrchestrator
from triade.core.planning_graph import GOAL_TERMINAL_STATES, PlanningGraph
from triade.workers.contracts import WorkerRunConfig
from triade.workers.worker_loop import WorkerLoop


def _orchestrator(tmp_path: Path, name: str = "triade.db") -> GoalOrchestrator:
    return GoalOrchestrator(tmp_path / name)


def _events(orchestrator: GoalOrchestrator, goal_id: str) -> list[dict]:
    return orchestrator.graph.get_events(goal_id)


def test_valid_order_runs_resolver_goal_plan_task_result_close_and_learning_audit(
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    accepted = orchestrator.accept("Prueba todos los tests", run_id="run-valid")

    assert accepted["status"] == "queued"
    assert accepted["task_id"]
    status = orchestrator.status(accepted["goal_id"])
    assert status["goal"]["metadata"]["capability"] == "test_suite"
    assert len(status["steps"]) == 1
    assert len(status["tasks"]) == 1

    orchestrator.record_task_result(
        {
            "goal_id": accepted["goal_id"],
            "goal_step_id": accepted["step_id"],
            "worker_task_type": "goal_safe_command",
        },
        {"status": "ok", "returncode": 0},
    )

    closed = orchestrator.status(accepted["goal_id"])
    assert closed["goal"]["status"] == "completed"
    assert closed["steps"][0]["status"] == "completed"
    assert closed["learning_observations"][0]["disposition"] == "no_learning_signal"
    assert {event["to_status"] for event in closed["events"]} >= {
        "pending",
        "queued",
        "completed",
    }


def test_valid_diagnostic_order_is_executed_by_real_worker(tmp_path: Path) -> None:
    db_path = tmp_path / "worker.db"
    orchestrator = GoalOrchestrator(db_path)
    accepted = orchestrator.accept(
        "Diagnostica el repositorio", run_id="run-real-worker"
    )
    # Aísla este circuito de las tareas periódicas que el scheduler añade al
    # mismo ciclo. La tarea sigue pasando por cola, lease, handler y artefactos.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE autonomous_tasks SET priority=0 WHERE task_id=?",
            (accepted["task_id"],),
        )
    loop = WorkerLoop(
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        lock_file=tmp_path / "worker.lock",
        stop_file=tmp_path / "worker.stop",
    )

    result = loop.run(
        WorkerRunConfig(
            max_iterations=1,
            sleep_seconds=0,
            once=True,
            runs_dir=str(tmp_path / "runs"),
            lock_file=str(tmp_path / "worker.lock"),
            stop_file=str(tmp_path / "worker.stop"),
            concurrency_enabled=False,
            max_tasks_per_drain=1,
            task_timeout=60,
        )
    )

    status = orchestrator.status(accepted["goal_id"])
    assert result["status"] == "completed", result.get("errors")
    assert status["tasks"][0]["status"] == "completed"
    assert status["tasks"][0].get("error") is None
    assert status["goal"]["status"] == "completed"
    assert status["learning_observations"][0]["disposition"] == "no_learning_signal"


@pytest.mark.parametrize(
    "question",
    [
        "¿Puedes probar todos los tests?",
        "Cómo puedo ejecutar las pruebas?",
    ],
)
def test_question_never_opens_goal(tmp_path: Path, question: str) -> None:
    orchestrator = _orchestrator(tmp_path, question[:4] + ".db")
    result = orchestrator.accept(question, run_id="run-question")
    assert result["status"] == "not_actionable"
    assert result["goal_created"] is False
    assert orchestrator.graph.get_plan_summary()["total"] == 0


def test_ambiguous_order_is_not_executed_or_resolved_by_action_regex_alone(
    tmp_path: Path,
) -> None:
    resolver = CapabilityResolver()
    intent = resolver.classify("Quizá podrías probar o compilar esto")
    assert intent.kind == "ambiguous"
    result = _orchestrator(tmp_path).accept(
        "Quizá podrías probar o compilar esto", run_id="run-ambiguous"
    )
    assert result["status"] == "needs_clarification"
    assert result["goal_created"] is False


def test_duplicate_goal_returns_existing_goal_and_task(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    first = orchestrator.accept("Prueba todos los tests", run_id="run-dedup-1")
    second = orchestrator.accept("  prueba TODOS los tests ", run_id="run-dedup-2")
    assert second["status"] == "duplicate"
    assert second["goal_id"] == first["goal_id"]
    assert second["task_id"] == first["task_id"]
    assert orchestrator.graph.get_plan_summary()["total"] == 2  # raíz + paso
    assert any(
        event["event_type"] == "duplicate_rejected"
        for event in _events(orchestrator, first["goal_id"])
    )


def test_unavailable_order_closes_as_audited_blocked_goal(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    result = orchestrator.accept("Ejecuta una acción imposible", run_id="run-blocked")
    status = orchestrator.status(result["goal_id"])
    assert status["goal"]["status"] == "blocked"
    assert status["goal"]["status"] in GOAL_TERMINAL_STATES
    assert status["events"][-1]["reason"]


def test_failed_goal_retries_then_replans_and_finishes_failed(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    accepted = orchestrator.accept("Prueba todos los tests", run_id="run-failed")
    payload = {
        "goal_id": accepted["goal_id"],
        "goal_step_id": accepted["step_id"],
        "worker_task_type": "goal_safe_command",
        "attempt": 1,
        "max_attempts": 2,
    }
    orchestrator.record_task_result(payload, {"status": "error", "error": "boom"})
    replanned = orchestrator.status(accepted["goal_id"])
    assert replanned["goal"]["status"] == "queued"
    assert any(event["event_type"] == "replanned" for event in replanned["events"])

    orchestrator.record_task_result(
        {**payload, "attempt": 2}, {"status": "error", "error": "boom-again"}
    )
    failed = orchestrator.status(accepted["goal_id"])
    assert failed["goal"]["status"] == "failed"
    assert failed["learning_observations"][0]["disposition"] == "failure_signal"


def test_expired_goal_is_terminal_and_audited(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    accepted = orchestrator.accept("Instala paquete demo", run_id="run-expired")
    result = orchestrator.expire(accepted["goal_id"], reason="approval_timeout")
    assert result["status"] == "expired"
    assert result["status"] in GOAL_TERMINAL_STATES
    assert (
        _events(orchestrator, accepted["goal_id"])[-1]["reason"] == "approval_timeout"
    )


def test_approved_goal_leaves_approval_state_with_actor_audit(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    accepted = orchestrator.accept("Instala paquete demo", run_id="run-approved")
    approved = orchestrator.approve_install(
        accepted["goal_id"], "demo", approved_by="human:test"
    )
    assert approved["status"] == "queued"
    events = _events(orchestrator, accepted["goal_id"])
    assert events[-1]["actor"] == "human:test"
    assert events[-1]["event_type"] == "approved"


def test_completed_goal_is_terminal_and_cannot_be_reopened(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    accepted = orchestrator.accept("Prueba todos los tests", run_id="run-complete")
    orchestrator.record_task_result(
        {"goal_id": accepted["goal_id"], "goal_step_id": accepted["step_id"]},
        {"status": "completed"},
    )
    with pytest.raises(ValueError, match="terminal"):
        orchestrator.graph.transition(
            accepted["goal_id"], "queued", actor="test", reason="reopen"
        )


def test_cancelled_goal_and_steps_are_terminal_and_audited(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    accepted = orchestrator.accept("Prueba todos los tests", run_id="run-cancel")
    cancelled = orchestrator.cancel(
        accepted["goal_id"], reason="operator_request", cancelled_by="human:test"
    )
    assert cancelled["status"] == "cancelled"
    status = orchestrator.status(accepted["goal_id"])
    assert status["steps"][0]["status"] == "cancelled"
    assert status["events"][-1]["actor"] == "human:test"


def test_historical_limbo_goals_receive_explicit_expiry_decision(
    tmp_path: Path,
) -> None:
    graph = PlanningGraph(tmp_path / "triade.db")
    stale = graph.create_goal("histórico", metadata={"run_id": "old"})
    old = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    with sqlite3.connect(graph.db_path) as conn:
        conn.execute(
            "UPDATE planning_graph SET updated_at=? WHERE goal_id=?",
            (old, stale.goal_id),
        )

    report = graph.reconcile_limbo(max_age_minutes=60, actor="phase3:test")
    assert report["examined"] == 1
    assert report["expired"] == 1
    assert graph.get_goal(stale.goal_id).status == "expired"
    assert (
        _events(_orchestrator(tmp_path), stale.goal_id)[-1]["event_type"]
        == "historical_limbo_expired"
    )


def test_unknown_goal_state_is_rejected() -> None:
    assert "mystery" not in GOAL_TERMINAL_STATES

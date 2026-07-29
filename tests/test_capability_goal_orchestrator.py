from triade.core.capability_resolver import CapabilityResolver
from triade.core.goal_orchestrator import GoalOrchestrator


def test_resolver_only_delegates_explicit_actions():
    resolver = CapabilityResolver()
    assert resolver.resolve("Hola, ¿cómo estás?").actionable is False
    research = resolver.resolve("Investiga documentación sobre materiales auxéticos")
    assert research.worker_task_type == "goal_research"
    assert research.requires_human_approval is False
    install = resolver.resolve("Instala este paquete y pruébalo")
    assert install.execution_mode == "human_approval"
    assert install.requires_human_approval is True


def test_orchestrator_persists_and_queues_safe_goal(tmp_path):
    orchestrator = GoalOrchestrator(tmp_path / "triade.db")
    result = orchestrator.accept("Prueba todos los tests", run_id="run-1")
    assert result["status"] == "queued"
    assert result["task_id"] is not None
    status = orchestrator.status(result["goal_id"])
    assert status["goal"]["status"] == "queued"
    assert status["steps"][0]["status"] == "queued"
    orchestrator.record_task_result(
        {"goal_id": result["goal_id"], "goal_step_id": result["step_id"]},
        {"status": "ok"},
    )
    assert orchestrator.status(result["goal_id"])["goal"]["status"] == "completed"


def test_install_goal_waits_for_human_approval(tmp_path):
    result = GoalOrchestrator(tmp_path / "triade.db").accept(
        "Instala una dependencia desconocida", run_id="run-2"
    )
    assert result["status"] == "awaiting_approval"
    assert result["task_id"] is None

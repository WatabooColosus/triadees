from __future__ import annotations

from pathlib import Path

from triade.capabilities.registry import CapabilityDefinition, CapabilityRegistry
from triade.core.central import PlanGraph, PlanStep
from triade.runtime.governed_plan_dispatcher import GovernedPlanDispatcher


def _register(db_path: Path, capability_id: str, *, state: str = "active") -> None:
    CapabilityRegistry(db_path).register(
        CapabilityDefinition(
            capability_id=capability_id,
            name=capability_id,
            domain="runtime",
            version="1",
            owner="central",
            component="governed_runtime",
            state=state,
            input_contract={"type": "object"},
            output_contract={"type": "object"},
            permissions=("execute",),
        )
    )


def _graph(
    description: str = "investiga documentación oficial",
) -> tuple[PlanGraph, PlanStep]:
    step = PlanStep(id="step-1", description=description)
    return PlanGraph(plan_id="plan-1", goal="test", steps=[step]), step


def test_plan_step_dispatches_to_autonomous_task(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    _register(db_path, "web_research")
    graph, step = _graph()
    dispatcher = GovernedPlanDispatcher(db_path)
    receipt = dispatcher.dispatch(graph, step)
    assert receipt.status == "queued"
    assert receipt.task_id is not None
    assert dispatcher.tasks.get(receipt.task_id)["status"] == "pending"


def test_missing_capability_blocks_step(tmp_path: Path) -> None:
    graph, step = _graph("crea un archivo nuevo")
    receipt = GovernedPlanDispatcher(tmp_path / "triade.db").dispatch(graph, step)
    assert receipt.status == "blocked"
    assert step.state == "blocked"
    assert receipt.task_id is None


def test_policy_denial_blocks_step(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    _register(db_path, "web_research", state="blocked")
    graph, step = _graph()
    receipt = GovernedPlanDispatcher(db_path).dispatch(graph, step)
    assert receipt.status == "blocked"
    assert "bloqueada" in step.error


def test_human_approval_required_does_not_execute(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    _register(db_path, "environment_install")
    graph, step = _graph("instala una dependencia")
    dispatcher = GovernedPlanDispatcher(db_path)
    receipt = dispatcher.dispatch(graph, step)
    assert receipt.approval_required is True
    assert receipt.task_id is None
    assert dispatcher.tasks.claim("worker") is None


def test_queued_step_is_not_completed(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    _register(db_path, "web_research")
    graph, step = _graph()
    receipt = GovernedPlanDispatcher(db_path).dispatch(graph, step)
    assert receipt.status == "queued"
    assert step.state == "queued"
    assert graph.status == "queued"


def test_completed_task_updates_plan_step(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    _register(db_path, "web_research")
    graph, step = _graph()
    dispatcher = GovernedPlanDispatcher(db_path)
    receipt = dispatcher.dispatch(graph, step)
    claimed = dispatcher.tasks.claim("worker")
    assert claimed and claimed["task_id"] == receipt.task_id
    result_ref = tmp_path / "result.json"
    result_ref.write_text("{}", encoding="utf-8")
    assert dispatcher.tasks.complete(
        claimed["task_id"], "worker", claimed["lease_generation"], str(result_ref)
    )
    dispatcher.synchronize(graph)
    assert step.state == "completed"
    assert graph.status == "completed"


def test_failed_task_updates_plan_step(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    _register(db_path, "web_research")
    graph, step = _graph()
    step.max_retries = 0
    dispatcher = GovernedPlanDispatcher(db_path)
    dispatcher.dispatch(graph, step)
    claimed = dispatcher.tasks.claim("worker")
    assert claimed
    dispatcher.tasks.fail(
        claimed["task_id"], "worker", claimed["lease_generation"], "failed"
    )
    dispatcher.synchronize(graph)
    assert step.state == "failed"
    assert graph.status == "failed"


def test_plan_closes_only_after_all_required_steps_terminal(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    _register(db_path, "web_research")
    first = PlanStep(id="first", description="investiga fuente uno")
    second = PlanStep(id="second", description="investiga fuente dos")
    graph = PlanGraph(plan_id="plan-many", goal="test", steps=[first, second])
    dispatcher = GovernedPlanDispatcher(db_path)
    dispatcher.dispatch(graph, first)
    dispatcher.dispatch(graph, second)
    one = dispatcher.tasks.claim("worker")
    assert one
    ref_one = tmp_path / "one.json"
    ref_one.write_text("{}", encoding="utf-8")
    dispatcher.tasks.complete(
        one["task_id"], "worker", one["lease_generation"], str(ref_one)
    )
    dispatcher.synchronize(graph)
    assert graph.status == "queued"
    two = dispatcher.tasks.claim("worker")
    assert two
    ref_two = tmp_path / "two.json"
    ref_two.write_text("{}", encoding="utf-8")
    dispatcher.tasks.complete(
        two["task_id"], "worker", two["lease_generation"], str(ref_two)
    )
    dispatcher.synchronize(graph)
    assert graph.status == "completed"

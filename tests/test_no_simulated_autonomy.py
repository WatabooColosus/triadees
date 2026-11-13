from triade.core.central import Central, PlanStep
from triade.core.contracts import PlanPacket


def test_central_does_not_complete_steps_without_executor() -> None:
    step = PlanStep(id="step-1", description="acción real pendiente")
    plan = PlanPacket(
        run_id="run-truth", goal="probar ejecución", structured_steps=[step]
    )
    result = Central(model_client=None).execute_plan_steps(plan)
    assert result["status"] == "requires_governed_executor"
    assert step.state == "blocked"
    assert step.error == "governed_executor_required"
    assert step.budget.used_cpu_seconds == 0
    assert step.budget.used_tokens == 0

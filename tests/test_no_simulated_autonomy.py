from __future__ import annotations

import sqlite3

from triade.core.central import Central, PlanStep
from triade.core.contracts import PlanPacket
from triade.os.autonomous_routines import AutonomousRoutines


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


def test_legacy_autonomous_claims_are_blocked_not_completed(tmp_path) -> None:
    path = tmp_path / "routines.db"
    routines = AutonomousRoutines(str(path))
    for routine_type in (
        "self_improvement",
        "autonomous_neuron_creation",
        "autonomous_training",
        "autonomous_verification",
        "autonomous_degradation",
        "auto_documentation",
        "autonomous_research",
    ):
        created = routines.create_routine(routine_type)
        result = routines.execute_routine(created["routine_id"])
        assert result["status"] == "blocked"
        assert result["result"]["status"] == "blocked"
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM autonomous_routines WHERE status='completed'"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM autonomous_improvements").fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM autonomous_documentation").fetchone()[0]
            == 0
        )


def test_autonomous_learning_observes_but_does_not_claim_learning(tmp_path) -> None:
    routines = AutonomousRoutines(str(tmp_path / "routines.db"))
    created = routines.create_routine("autonomous_learning")
    result = routines.execute_routine(created["routine_id"])
    payload = result["result"]
    assert result["status"] != "completed"
    assert payload["status"] in {"observed", "failed"}
    assert payload["edges_created"] == 0
    assert payload["compressed"] == 0


def test_legacy_observation_is_persisted_as_observed(tmp_path) -> None:
    path = tmp_path / "routines.db"
    routines = AutonomousRoutines(str(path))
    created = routines.create_routine("health_maintenance")
    result = routines.execute_routine(created["routine_id"])
    assert result["status"] == "observed"
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT status FROM autonomous_routines WHERE routine_id=?",
            (created["routine_id"],),
        ).fetchone()
    assert row == ("observed",)


def test_legacy_improvement_requires_evidence_and_rollback(tmp_path) -> None:
    routines = AutonomousRoutines(str(tmp_path / "routines.db"))
    result = routines.record_improvement(
        "routine-x", "quality", "unverified claim", before={}, after={}
    )
    assert result["status"] == "blocked"
    assert result["improvement_id"] is None
    assert routines.improvements() == []

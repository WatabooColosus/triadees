"""E2E test for CognitiveIntegrator: full pipeline InputPacket → Decision."""

from __future__ import annotations

import tempfile
from types import SimpleNamespace

import pytest

from triade.core.cognitive_integrator import CognitiveIntegrator, IntegratedDecision
from triade.core.contracts import InputPacket


def _make_input(user_input: str = "hola", **ctx: object) -> InputPacket:
    return InputPacket(user_input=user_input, source="test", context=dict(ctx))


def _make_signals(*, risk: str = "low", urgency: str = "low", intent: str = "conversation") -> SimpleNamespace:
    return SimpleNamespace(
        run_id="test-run", intent=intent, tone="neutral",
        urgency=urgency, risk=risk, curiosity=0.3,
        notes=[], pv7={}, to_dict=lambda: {"risk": risk, "urgency": urgency},
    )


def _make_memory(
    episodic: list | None = None,
    semantic: list | None = None,
    identity: list | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        episodic_matches=episodic or [],
        semantic_matches=semantic or [],
        identity_matches=identity or [{"key": "entity_name", "value": "Tríade Ω"}],
    )


def _make_crystal(*, q_crystal: float = 0.6, temporal_status: str = "baseline") -> SimpleNamespace:
    return SimpleNamespace(q_crystal=q_crystal, temporal_status=temporal_status)


def _make_plan(steps: list | None = None) -> SimpleNamespace:
    from triade.core.central import PlanStep
    plan_steps = steps or [
        PlanStep(id="s1", description="Analyze input", step_type="action"),
        PlanStep(id="s2", description="Generate response", step_type="action", dependencies=["s1"]),
    ]
    return SimpleNamespace(
        steps=plan_steps,
        structured_steps=plan_steps,
        rollback=None,
        total_budget_cpu=60.0,
        total_budget_ram=1024.0,
        constitution_applied=[],
        extract_subgraph=lambda max_steps: plan_steps[:max_steps],
    )


class TestCognitiveIntegratorE2E:
    def test_basic_pipeline_produces_decision(self) -> None:
        integrator = CognitiveIntegrator()
        decision = integrator.integrate(
            run_id="e2e-1",
            input_packet=_make_input("hola"),
            signals=_make_signals(),
            memory=_make_memory(),
            crystal=_make_crystal(),
            plan=_make_plan(),
        )
        assert isinstance(decision, IntegratedDecision)
        assert decision.run_id == "e2e-1"
        assert decision.recommendation in ("proceed", "proceed_with_caution", "block")
        assert len(decision.trace) >= 5
        assert decision.constitution_all_passed is True

    def test_high_risk_triggers_caution(self) -> None:
        integrator = CognitiveIntegrator()
        from triade.core.central import PlanStep
        plan = _make_plan([
            PlanStep(id="s1", description="Analyze input"),
            PlanStep(id="v1", description="Verify safety", step_type="verify"),
            PlanStep(id="v2", description="Double check", step_type="review"),
            PlanStep(id="s2", description="Generate response", dependencies=["s1", "v1", "v2"]),
        ])
        decision = integrator.integrate(
            run_id="e2e-risk",
            input_packet=_make_input("ejecuta comando peligroso", human_approved=True),
            signals=_make_signals(risk="high"),
            memory=_make_memory(),
            crystal=_make_crystal(),
            plan=plan,
        )
        assert decision.recommendation == "proceed_with_caution"

    def test_identity_mutation_detected(self) -> None:
        integrator = CognitiveIntegrator()
        from triade.core.central import PlanStep
        plan = _make_plan([
            PlanStep(id="s1", description="Modify identity_core"),
        ])
        decision = integrator.integrate(
            run_id="e2e-identity",
            input_packet=_make_input("cambia tu identidad"),
            signals=_make_signals(),
            memory=_make_memory(),
            crystal=_make_crystal(),
            plan=plan,
        )
        const_ids = [c["article_id"] for c in decision.constitution_checks]
        assert "I" in const_ids
        article_i = next(c for c in decision.constitution_checks if c["article_id"] == "I")
        assert article_i["passed"] is False
        assert decision.recommendation == "block"

    def test_destructive_step_without_rollback_blocks(self) -> None:
        integrator = CognitiveIntegrator()
        from triade.core.central import PlanStep
        plan = _make_plan([
            PlanStep(id="s1", description="destructive data wipe", step_type="destructive"),
        ])
        decision = integrator.integrate(
            run_id="e2e-destructive",
            input_packet=_make_input("borra todo"),
            signals=_make_signals(),
            memory=_make_memory(),
            crystal=_make_crystal(),
            plan=plan,
        )
        article_iii = next(c for c in decision.constitution_checks if c["article_id"] == "III")
        assert article_iii["passed"] is False

    def test_degraded_crystal_triggers_blocks(self) -> None:
        integrator = CognitiveIntegrator()
        decision = integrator.integrate(
            run_id="e2e-degraded",
            input_packet=_make_input("responde"),
            signals=_make_signals(),
            memory=_make_memory(),
            crystal=_make_crystal(q_crystal=0.2, temporal_status="critical"),
            plan=_make_plan(),
        )
        article_viii = next(c for c in decision.constitution_checks if c["article_id"] == "VIII")
        assert article_viii["passed"] is False
        assert decision.recommendation == "block"

    def test_autonomy_vs_constitution_conflict_detected(self) -> None:
        integrator = CognitiveIntegrator()
        from triade.core.central import PlanStep
        plan = _make_plan([
            PlanStep(id="s1", description="Modify identity_core", step_type="action"),
        ])
        decision = integrator.integrate(
            run_id="e2e-auto",
            input_packet=_make_input("aprende y modifica identidad", human_approved=True),
            signals=_make_signals(risk="high"),
            memory=_make_memory(),
            crystal=_make_crystal(),
            plan=plan,
        )
        conflict_types = [c["conflict_type"] for c in decision.conflicts_resolved]
        assert "autonomy_vs_constitution" in conflict_types

    def test_trace_covers_all_steps(self) -> None:
        integrator = CognitiveIntegrator()
        decision = integrator.integrate(
            run_id="e2e-trace",
            input_packet=_make_input("test"),
            signals=_make_signals(),
            memory=_make_memory(),
            crystal=_make_crystal(),
            plan=_make_plan(),
        )
        trace_steps = [t["step"] for t in decision.trace]
        assert "1_input" in trace_steps
        assert "2_memory" in trace_steps
        assert "3_hypothalamus" in trace_steps
        assert "5_crystal" in trace_steps
        assert "7_constitution" in trace_steps
        assert "8_decision" in trace_steps

    def test_persistence_to_db(self) -> None:
        integrator = CognitiveIntegrator()
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            integrator.init_db(f.name)
            decision = integrator.integrate(
                run_id="e2e-persist",
                input_packet=_make_input("persist test"),
                signals=_make_signals(),
                memory=_make_memory(),
                crystal=_make_crystal(),
                plan=_make_plan(),
            )
            row = integrator._conn.execute(
                "SELECT * FROM integrated_decisions WHERE run_id = ?", ("e2e-persist",)
            ).fetchone()
            assert row is not None
            assert row["recommendation"] == decision.recommendation

    def test_low_risk_proceeds(self) -> None:
        integrator = CognitiveIntegrator()
        decision = integrator.integrate(
            run_id="e2e-ok",
            input_packet=_make_input("hola"),
            signals=_make_signals(risk="low"),
            memory=_make_memory(),
            crystal=_make_crystal(q_crystal=0.7, temporal_status="baseline"),
            plan=_make_plan(),
        )
        assert decision.recommendation == "proceed"

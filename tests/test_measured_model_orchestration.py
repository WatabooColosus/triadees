from pathlib import Path

from triade.models.measured_orchestration import (
    MeasuredModelOrchestrator,
    ModelCapability,
    RouteRequirements,
)


def capability(
    model: str, role: str, quality: float, **values: object
) -> ModelCapability:
    return ModelCapability(
        model=model,
        roles=frozenset({role}),
        quality={role: quality},
        latency_ms=float(values.get("latency_ms", 10)),
        vram_gb=float(values.get("vram_gb", 1)),
        ram_gb=float(values.get("ram_gb", 2)),
        available=bool(values.get("available", True)),
        private=bool(values.get("private", True)),
        context_tokens=int(values.get("context_tokens", 8192)),
    )


def requirements() -> RouteRequirements:
    return RouteRequirements(100, 8, 16, True, 4096)


def test_routes_by_quality_with_resource_constraints(tmp_path: Path) -> None:
    models = [
        capability("coder-small", "coder", 0.8),
        capability("coder-best", "coder", 0.9),
    ]
    route = MeasuredModelOrchestrator(tmp_path / "db", models).route(
        "coder", requirements()
    )
    assert route.selected_model == "coder-best"
    assert route.reason == "highest_measured_role_quality_within_resource_policy"


def test_unavailable_or_oversized_model_uses_explicit_fallback(tmp_path: Path) -> None:
    models = [capability("vision", "vision", 1.0, vram_gb=20)]
    route = MeasuredModelOrchestrator(tmp_path / "db", models).route(
        "vision", requirements(), fallback="cpu-vision"
    )
    assert route.fallback_used is True
    assert route.selected_model == "cpu-vision"


def test_gpu_switch_records_safe_unload(tmp_path: Path) -> None:
    models = [capability("planner", "planner", 1.0), capability("coder", "coder", 1.0)]
    orchestrator = MeasuredModelOrchestrator(tmp_path / "db", models)
    assert (
        orchestrator.route("planner", requirements()).unload_previous_gpu_model is False
    )
    assert orchestrator.route("coder", requirements()).unload_previous_gpu_model is True


def test_missing_ab_never_adopts(tmp_path: Path) -> None:
    orchestrator = MeasuredModelOrchestrator(tmp_path / "db", [])
    decision = orchestrator.evaluate_adoption(
        baseline_model="single",
        routes=[],
        baseline_metrics=None,
        candidate_metrics=None,
    )
    assert decision["adopted"] is False
    assert decision["rollback_ref"] == "model-routing:restore:single"


def test_ab_adopts_only_measured_resource_improvement(tmp_path: Path) -> None:
    orchestrator = MeasuredModelOrchestrator(tmp_path / "db", [])
    decision = orchestrator.evaluate_adoption(
        baseline_model="single",
        routes=[],
        baseline_metrics={"quality": 0.8, "resource_cost": 10.0},
        candidate_metrics={"quality": 0.8, "resource_cost": 8.0},
    )
    assert decision["adopted"] is True


def test_ab_adopts_significant_quality_gain_only_within_resource_budget(
    tmp_path: Path,
) -> None:
    orchestrator = MeasuredModelOrchestrator(tmp_path / "db", [])
    accepted = orchestrator.evaluate_adoption(
        baseline_model="single",
        routes=[],
        baseline_metrics={"quality": 0.7, "resource_cost": 10.0},
        candidate_metrics={"quality": 0.85, "resource_cost": 15.0},
    )
    rejected = orchestrator.evaluate_adoption(
        baseline_model="single",
        routes=[],
        baseline_metrics={"quality": 0.7, "resource_cost": 10.0},
        candidate_metrics={"quality": 0.85, "resource_cost": 21.0},
    )
    assert accepted["adopted"] is True
    assert accepted["reason"] == "measured_quality_improvement_within_resource_budget"
    assert rejected["adopted"] is False

from pathlib import Path

from triade.capabilities import CapabilityDefinition, CapabilityRegistry
from triade.core.observability_view import TriadeObservabilityView


def test_unified_observability_exposes_capability_registry(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    registry = CapabilityRegistry(db_path)
    registry.register(
        CapabilityDefinition(
            capability_id="learning",
            name="Learning",
            domain="cognition",
            version="1.0.0",
            owner="central",
            component="triade.learning",
        )
    )

    payload = TriadeObservabilityView(db_path=db_path, runs_dir=tmp_path / "runs").build(limit=5)

    assert payload["capability_registry"]["total"] == 1
    assert payload["capability_registry"]["by_domain"] == {"cognition": 1}
    assert payload["capability_registry"]["capabilities"][0]["capability_id"] == "learning"


def test_blocked_capability_degrades_global_observability(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    CapabilityRegistry(db_path).register(
        CapabilityDefinition(
            capability_id="unsafe_adapter",
            name="Unsafe Adapter",
            domain="integration",
            version="1.0.0",
            owner="central",
            component="triade.adapters.unsafe",
            state="blocked",
        )
    )

    payload = TriadeObservabilityView(db_path=db_path, runs_dir=tmp_path / "runs").build(limit=5)

    assert payload["status"] == "degraded"
    assert any("Capability Registry requiere atención" in warning for warning in payload["warnings"])

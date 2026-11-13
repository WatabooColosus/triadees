from pathlib import Path

import pytest

from triade.capabilities import CapabilityDefinition, CapabilityRegistry


def test_register_and_query_capability(tmp_path: Path) -> None:
    registry = CapabilityRegistry(tmp_path / "triade.db")
    capability = CapabilityDefinition(
        capability_id="learning",
        name="Learning",
        domain="cognition",
        version="1.0.0",
        owner="central",
        component="triade.learning",
        evaluation_suites=("learning-promotion@1.0.0",),
        rollback_policy="learning-rollback",
        critical=True,
    )

    registry.register(capability)

    stored = registry.get("learning", "1.0.0")
    assert stored is not None
    assert stored["critical"] is True
    assert stored["state"] == "experimental"


def test_critical_capability_requires_suite_and_rollback(tmp_path: Path) -> None:
    registry = CapabilityRegistry(tmp_path / "triade.db")
    capability = CapabilityDefinition(
        capability_id="identity_core",
        name="Identity Core",
        domain="core",
        version="1.0.0",
        owner="central",
        component="triade.core",
        critical=True,
    )

    with pytest.raises(ValueError, match="requiere suite y rollback"):
        registry.register(capability)


def test_missing_dependency_is_rejected(tmp_path: Path) -> None:
    registry = CapabilityRegistry(tmp_path / "triade.db")
    capability = CapabilityDefinition(
        capability_id="semantic_memory",
        name="Semantic Memory",
        domain="memory",
        version="1.0.0",
        owner="bodega",
        component="triade.memory",
        dependencies=("identity_core",),
    )

    with pytest.raises(ValueError, match="dependencias inexistentes"):
        registry.register(capability)


def test_state_changes_and_filters(tmp_path: Path) -> None:
    registry = CapabilityRegistry(tmp_path / "triade.db")
    capability = CapabilityDefinition(
        capability_id="observability",
        name="Observability",
        domain="operations",
        version="1.0.0",
        owner="central",
        component="triade.core.observability_view",
    )
    registry.register(capability)

    updated = registry.set_state("observability", "1.0.0", "active")

    assert updated["state"] == "active"
    assert len(registry.list(state="active")) == 1
    assert len(registry.list(domain="operations")) == 1

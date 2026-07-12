from pathlib import Path

import pytest

from triade.capabilities import CapabilityDefinition, CapabilityRegistry


def make_capability(capability_id: str, dependencies: tuple[str, ...] = ()) -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_id=capability_id,
        name=capability_id.replace("_", " ").title(),
        domain="testing",
        version="1.0.0",
        owner="central",
        component=f"triade.{capability_id}",
        dependencies=dependencies,
    )


def test_registration_and_state_changes_are_audited(tmp_path: Path) -> None:
    registry = CapabilityRegistry(tmp_path / "triade.db")
    registry.register(make_capability("observability"))

    registry.set_state("observability", "1.0.0", "active")

    history = registry.history("observability", "1.0.0")
    assert [entry["action"] for entry in history] == ["registered", "state_changed"]
    assert history[1]["payload"]["from"] == "experimental"
    assert history[1]["payload"]["to"] == "active"


def test_history_is_isolated_by_version(tmp_path: Path) -> None:
    registry = CapabilityRegistry(tmp_path / "triade.db")
    registry.register(make_capability("learning"))
    registry.register(
        CapabilityDefinition(
            capability_id="learning",
            name="Learning",
            domain="testing",
            version="2.0.0",
            owner="central",
            component="triade.learning",
        )
    )

    assert len(registry.history("learning")) == 2
    assert len(registry.history("learning", "1.0.0")) == 1
    assert len(registry.history("learning", "2.0.0")) == 1


def test_indirect_dependency_cycle_is_rejected(tmp_path: Path) -> None:
    registry = CapabilityRegistry(tmp_path / "triade.db")
    registry.register(make_capability("a"))
    registry.register(make_capability("b", ("a",)))
    registry.register(make_capability("c", ("b",)))

    with pytest.raises(ValueError, match="ciclo de dependencias"):
        registry.register(
            CapabilityDefinition(
                capability_id="a",
                name="A",
                domain="testing",
                version="2.0.0",
                owner="central",
                component="triade.a",
                dependencies=("c",),
            )
        )


def test_non_cyclic_dependency_chain_is_allowed(tmp_path: Path) -> None:
    registry = CapabilityRegistry(tmp_path / "triade.db")
    registry.register(make_capability("identity_core"))
    registry.register(make_capability("semantic_memory", ("identity_core",)))
    registry.register(make_capability("learning", ("semantic_memory",)))

    assert registry.get("learning", "1.0.0") is not None

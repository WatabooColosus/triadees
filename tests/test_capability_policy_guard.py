from pathlib import Path

import pytest

from triade.capabilities import CapabilityDefinition, CapabilityPolicyGuard, CapabilityRegistry


def executable(capability_id: str, *, state: str = "active", permissions: tuple[str, ...] = ("read", "execute")) -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_id=capability_id,
        name=capability_id,
        domain="testing",
        version="1.0.0",
        owner="central",
        component=f"triade.{capability_id}",
        state=state,
        input_contract={"type": "object", "required": ["input"]},
        output_contract={"type": "object", "required": ["result"]},
        permissions=permissions,
    )


def test_executable_capability_requires_input_and_output_contracts(tmp_path: Path) -> None:
    registry = CapabilityRegistry(tmp_path / "triade.db")
    definition = CapabilityDefinition(
        capability_id="worker",
        name="Worker",
        domain="testing",
        version="1.0.0",
        owner="central",
        component="triade.worker",
        permissions=("execute",),
    )

    with pytest.raises(ValueError, match="requiere contratos"):
        registry.register(definition)


def test_invalid_permission_is_rejected(tmp_path: Path) -> None:
    registry = CapabilityRegistry(tmp_path / "triade.db")
    definition = CapabilityDefinition(
        capability_id="worker",
        name="Worker",
        domain="testing",
        version="1.0.0",
        owner="central",
        component="triade.worker",
        permissions=("root",),
    )

    with pytest.raises(ValueError, match="permisos inválidos"):
        registry.register(definition)


def test_blocked_capability_rejects_every_action(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    CapabilityRegistry(db_path).register(executable("blocked_worker", state="blocked"))
    guard = CapabilityPolicyGuard(db_path)

    assert guard.decide("blocked_worker", "read").allowed is False
    assert guard.decide("blocked_worker", "execute").reason == "capacidad bloqueada"


def test_deprecated_capability_cannot_be_promoted(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    CapabilityRegistry(db_path).register(
        executable("legacy_worker", state="deprecated", permissions=("read", "execute", "promote"))
    )

    decision = CapabilityPolicyGuard(db_path).decide("legacy_worker", "promote")

    assert decision.allowed is False
    assert "deprecated" in decision.reason


def test_permission_guard_allows_only_declared_actions(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    CapabilityRegistry(db_path).register(executable("reader", permissions=("read",)))
    guard = CapabilityPolicyGuard(db_path)

    assert guard.decide("reader", "read").allowed is True
    assert guard.decide("reader", "write").allowed is False
    with pytest.raises(PermissionError, match="permiso no concedido"):
        guard.require("reader", "write")

"""Registro idempotente de capacidades núcleo de Tríade Ω."""

from __future__ import annotations

from pathlib import Path

from .registry import CapabilityDefinition, CapabilityRegistry


CORE_CAPABILITIES = (
    CapabilityDefinition(
        capability_id="measurement-core",
        name="Measurement Core",
        domain="evaluation",
        version="1.0.0",
        owner="central",
        component="triade.evaluation",
        state="active",
        critical=True,
        evaluation_suites=("measurement-core@1.0.0",),
        rollback_policy="measurement-core-rollback",
        permissions=("read", "execute"),
        input_contract={"type": "object"},
        output_contract={"type": "object"},
    ),
    CapabilityDefinition(
        capability_id="regression-gate",
        name="Regression Gate",
        domain="safety",
        version="1.0.0",
        owner="central",
        component="triade.regression",
        state="active",
        critical=True,
        dependencies=("measurement-core",),
        evaluation_suites=("triade-core-safety@1.0.0",),
        rollback_policy="regression-gate-rollback",
        permissions=("read", "execute"),
        input_contract={"type": "object"},
        output_contract={"type": "object"},
    ),
    CapabilityDefinition(
        capability_id="learning-promotion",
        name="Learning Promotion",
        domain="learning",
        version="1.0.0",
        owner="central",
        component="triade.learning.evidence_bridge",
        state="active",
        critical=True,
        dependencies=("measurement-core", "regression-gate"),
        evaluation_suites=("learning-promotion@1.0.0",),
        rollback_policy="learning-promotion-rollback",
        permissions=("read", "execute", "promote"),
        input_contract={"type": "object", "required": ["candidate_id"]},
        output_contract={"type": "object", "required": ["decision"]},
    ),
    CapabilityDefinition(
        capability_id="capability-registry",
        name="Capability Registry",
        domain="governance",
        version="1.0.0",
        owner="central",
        component="triade.capabilities",
        state="active",
        critical=True,
        dependencies=("regression-gate",),
        evaluation_suites=("triade-core-safety@1.0.0",),
        rollback_policy="capability-registry-rollback",
        permissions=("read", "write", "execute"),
        input_contract={"type": "object"},
        output_contract={"type": "object"},
    ),
)


def bootstrap_core_capabilities(db_path: str | Path = "triade/memory/triade.db") -> list[dict]:
    registry = CapabilityRegistry(db_path)
    registered: list[dict] = []
    for definition in CORE_CAPABILITIES:
        current = registry.get(definition.capability_id, definition.version)
        if current is None:
            current = registry.register(definition)
        registered.append(current)
    return registered

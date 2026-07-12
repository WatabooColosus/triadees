"""Bootstrap idempotente de capacidades núcleo de Tríade Ω."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .registry import CapabilityDefinition, CapabilityRegistry


def core_capabilities() -> tuple[CapabilityDefinition, ...]:
    object_contract: dict[str, Any] = {"type": "object"}
    return (
        CapabilityDefinition(
            capability_id="identity_core",
            name="Identity Core",
            domain="identity",
            version="1.0.0",
            owner="central",
            component="triade.core.identity",
            state="active",
            critical=True,
            evaluation_suites=("triade-core-safety@1.0.0",),
            rollback_policy="identity-core-rollback",
            input_contract=object_contract,
            output_contract=object_contract,
            permissions=("read", "execute"),
        ),
        CapabilityDefinition(
            capability_id="semantic_memory",
            name="Semantic Memory",
            domain="memory",
            version="1.0.0",
            owner="bodega",
            component="triade.memory.semantic_store",
            state="active",
            critical=True,
            dependencies=("identity_core",),
            evaluation_suites=("semantic-memory-governance@1.0.0",),
            rollback_policy="semantic-memory-rollback",
            input_contract=object_contract,
            output_contract=object_contract,
            permissions=("read", "write", "execute"),
        ),
        CapabilityDefinition(
            capability_id="learning_promotion",
            name="Learning Promotion",
            domain="learning",
            version="1.0.0",
            owner="central",
            component="triade.learning.evidence_bridge",
            state="active",
            critical=True,
            dependencies=("identity_core", "semantic_memory"),
            evaluation_suites=("learning-promotion@1.0.0",),
            rollback_policy="learning-promotion-rollback",
            input_contract=object_contract,
            output_contract=object_contract,
            permissions=("read", "execute", "promote"),
        ),
        CapabilityDefinition(
            capability_id="regression_gate",
            name="Regression Gate",
            domain="evaluation",
            version="1.0.0",
            owner="central",
            component="triade.regression.gate",
            state="active",
            critical=True,
            dependencies=("identity_core",),
            evaluation_suites=("triade-core-safety@1.0.0",),
            rollback_policy="regression-gate-rollback",
            input_contract=object_contract,
            output_contract=object_contract,
            permissions=("read", "write", "execute"),
        ),
    )


def bootstrap_core_capabilities(db_path: str | Path = "triade/memory/triade.db") -> list[dict[str, Any]]:
    registry = CapabilityRegistry(db_path)
    results: list[dict[str, Any]] = []
    for definition in core_capabilities():
        existing = registry.get(definition.capability_id, definition.version)
        if existing is not None:
            results.append(existing)
            continue
        results.append(registry.register(definition))
    return results

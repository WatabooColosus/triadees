from __future__ import annotations

import json
from pathlib import Path

from triade.capabilities import (
    CapabilityDefinition,
    CapabilityObservability,
    CapabilityRegistry,
    CapabilityRegistryExporter,
)


def capability(capability_id: str, *, state: str = "experimental", critical: bool = False) -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_id=capability_id,
        name=capability_id,
        domain="testing",
        version="1.0.0",
        owner="central",
        component=f"triade.{capability_id}",
        state=state,
        critical=critical,
        evaluation_suites=("triade-core-safety@1.0.0",) if critical else (),
        rollback_policy="core-rollback" if critical else None,
    )


def test_export_is_deterministic_and_contains_history(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    registry = CapabilityRegistry(db_path)
    registry.register(capability("identity_core", critical=True))
    registry.set_state("identity_core", "1.0.0", "active")
    exporter = CapabilityRegistryExporter(db_path)

    first = exporter.build()
    second = exporter.build()

    assert first == second
    assert len(first["sha256"]) == 64
    assert [event["action"] for event in first["history"]["identity_core"]] == [
        "registered",
        "state_changed",
    ]


def test_export_write_produces_valid_json(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    CapabilityRegistry(db_path).register(capability("learning"))
    output = CapabilityRegistryExporter(db_path).write(tmp_path / "artifacts" / "capabilities.json")

    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "1.0.0"
    assert payload["capabilities"][0]["capability_id"] == "learning"


def test_observability_reports_blocked_capabilities_as_attention(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    registry = CapabilityRegistry(db_path)
    registry.register(capability("learning", state="active"))
    registry.register(capability("unsafe_adapter", state="blocked"))

    snapshot = CapabilityObservability(db_path).snapshot()

    assert snapshot["status"] == "attention"
    assert snapshot["total"] == 2
    assert snapshot["blocked"] == 1
    assert snapshot["by_state"] == {"active": 1, "blocked": 1}


def test_observability_empty_registry_is_explicit(tmp_path: Path) -> None:
    snapshot = CapabilityObservability(tmp_path / "triade.db").snapshot()

    assert snapshot["status"] == "empty"
    assert snapshot["total"] == 0

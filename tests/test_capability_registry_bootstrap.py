from pathlib import Path

from triade.capabilities import (
    CapabilityPolicyGuard,
    CapabilityRegistry,
    bootstrap_core_capabilities,
)


def test_core_capability_bootstrap_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"

    first = bootstrap_core_capabilities(db_path)
    second = bootstrap_core_capabilities(db_path)

    assert len(first) == 4
    assert second == first
    registry = CapabilityRegistry(db_path)
    assert registry.get("identity_core")["state"] == "active"
    assert registry.get("semantic_memory")["dependencies"] == ["identity_core"]
    assert registry.get("learning_promotion")["permissions"] == ["read", "execute", "promote"]


def test_learning_promotion_core_capability_allows_promotion(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    bootstrap_core_capabilities(db_path)

    decision = CapabilityPolicyGuard(db_path).decide("learning_promotion", "promote")

    assert decision.allowed is True
    assert decision.reason == "permitido"


def test_deprecating_learning_promotion_blocks_future_promotions(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    bootstrap_core_capabilities(db_path)
    registry = CapabilityRegistry(db_path)
    registry.set_state("learning_promotion", "1.0.0", "deprecated")

    decision = CapabilityPolicyGuard(db_path).decide("learning_promotion", "promote")

    assert decision.allowed is False
    assert "deprecated" in decision.reason

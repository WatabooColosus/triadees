from pathlib import Path

import pytest

from triade.capabilities.bootstrap import bootstrap_core_capabilities
from triade.capabilities.learning_bridge import GovernedLearningEvidenceBridge
from triade.capabilities.registry import CapabilityRegistry


def test_core_capabilities_bootstrap_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"

    first = bootstrap_core_capabilities(db_path)
    second = bootstrap_core_capabilities(db_path)

    assert [item["capability_id"] for item in first] == [
        "measurement-core",
        "regression-gate",
        "learning-promotion",
        "capability-registry",
    ]
    assert first == second
    assert len(CapabilityRegistry(db_path).list()) == 4


def test_governed_bridge_blocks_promotion_when_capability_is_blocked(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    bridge = GovernedLearningEvidenceBridge(db_path)
    CapabilityRegistry(db_path).set_state("learning-promotion", "1.0.0", "blocked")

    with pytest.raises(PermissionError, match="capacidad bloqueada"):
        bridge.require_improvement("candidate-1")


def test_governed_bridge_checks_capability_before_evidence(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    bridge = GovernedLearningEvidenceBridge(db_path)

    with pytest.raises(ValueError, match="No existe evidencia"):
        bridge.require_improvement("missing-candidate")

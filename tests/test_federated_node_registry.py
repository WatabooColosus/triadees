from pathlib import Path

import pytest

from triade.federation import FederatedNodeIdentity, FederatedNodeRegistry


def node(**overrides):
    payload = {
        "node_id": "node-medellin-01",
        "display_name": "Nodo Medellín",
        "endpoint": "https://node.example.test",
        "public_key": "PUBLIC-KEY-ONE",
        "capabilities": ("research_verified",),
        "permissions": ("discover", "submit_work", "return_evidence"),
    }
    payload.update(overrides)
    return FederatedNodeIdentity(**payload)


def test_registers_pending_node_with_fingerprint(tmp_path: Path) -> None:
    registry = FederatedNodeRegistry(tmp_path / "triade.db")
    created = registry.register(node())

    assert created["state"] == "pending"
    assert created["trust_score"] == 0.0
    assert len(created["key_fingerprint"]) == 64
    assert registry.authorize(
        created["node_id"], capability="research_verified", permission="submit_work"
    ) is False


def test_duplicate_node_or_key_is_rejected(tmp_path: Path) -> None:
    registry = FederatedNodeRegistry(tmp_path / "triade.db")
    registry.register(node())

    with pytest.raises(ValueError, match="ya registrados"):
        registry.register(node())

    with pytest.raises(ValueError, match="ya registrados"):
        registry.register(node(node_id="node-other"))


def test_trusted_node_is_authorized_only_for_declared_scope(tmp_path: Path) -> None:
    registry = FederatedNodeRegistry(tmp_path / "triade.db")
    registry.register(node())
    trusted = registry.transition(
        "node-medellin-01",
        "trusted",
        actor="human-operator",
        reason="clave verificada fuera de banda",
        trust_score=0.8,
    )

    assert trusted["state"] == "trusted"
    assert registry.authorize(
        "node-medellin-01", capability="research_verified", permission="submit_work"
    ) is True
    assert registry.authorize(
        "node-medellin-01", capability="unknown", permission="submit_work"
    ) is False
    assert registry.authorize(
        "node-medellin-01", capability="research_verified", permission="admin"
    ) is False


def test_low_trust_cannot_be_promoted(tmp_path: Path) -> None:
    registry = FederatedNodeRegistry(tmp_path / "triade.db")
    registry.register(node())

    with pytest.raises(ValueError, match="trust_score >= 0.5"):
        registry.transition(
            "node-medellin-01",
            "trusted",
            actor="human-operator",
            reason="insuficiente",
            trust_score=0.4,
        )


def test_quarantine_and_revocation_disable_authorization(tmp_path: Path) -> None:
    registry = FederatedNodeRegistry(tmp_path / "triade.db")
    registry.register(node())
    registry.transition(
        "node-medellin-01",
        "trusted",
        actor="human-operator",
        reason="verificado",
        trust_score=0.9,
    )
    registry.transition(
        "node-medellin-01",
        "quarantined",
        actor="safety-monitor",
        reason="respuesta inválida",
        trust_score=0.2,
    )

    assert registry.authorize(
        "node-medellin-01", capability="research_verified", permission="submit_work"
    ) is False

    revoked = registry.transition(
        "node-medellin-01",
        "revoked",
        actor="human-operator",
        reason="clave comprometida",
        trust_score=0.0,
    )
    assert revoked["state"] == "revoked"
    with pytest.raises(ValueError, match="transición inválida"):
        registry.transition(
            "node-medellin-01",
            "pending",
            actor="human-operator",
            reason="no permitido",
        )


def test_history_is_auditable(tmp_path: Path) -> None:
    registry = FederatedNodeRegistry(tmp_path / "triade.db")
    registry.register(node(), actor="bootstrap")
    registry.transition(
        "node-medellin-01",
        "trusted",
        actor="human-operator",
        reason="verificado",
        trust_score=0.75,
    )

    history = registry.history("node-medellin-01")
    assert [event["action"] for event in history] == ["registered", "state:trusted"]
    assert history[1]["actor"] == "human-operator"

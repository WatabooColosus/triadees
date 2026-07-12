from dataclasses import replace
from pathlib import Path

import pytest

from triade.federation import (
    FederatedEnvelope,
    FederatedExchangeStore,
    FederatedNodeIdentity,
    FederatedNodeRegistry,
    HMACEnvelopeAuthenticator,
)


SECRET = b"0123456789abcdef0123456789abcdef"
NOW = 1_800_000_000


def prepare(db_path: Path) -> tuple[FederatedExchangeStore, HMACEnvelopeAuthenticator]:
    registry = FederatedNodeRegistry(db_path)
    registry.register(
        FederatedNodeIdentity(
            node_id="remote-01",
            display_name="Remote 01",
            endpoint="https://remote.example.test",
            public_key="REMOTE-PUBLIC-KEY",
            capabilities=("research_verified",),
            permissions=("submit_work",),
        )
    )
    registry.transition(
        "remote-01",
        "trusted",
        actor="human-operator",
        reason="clave verificada",
        trust_score=0.9,
    )
    authenticator = HMACEnvelopeAuthenticator(lambda node_id: SECRET)
    store = FederatedExchangeStore(
        db_path,
        local_node_id="local-01",
        authenticator=authenticator,
        clock=lambda: NOW,
        max_ttl_seconds=120,
        max_clock_skew_seconds=10,
    )
    return store, authenticator


def envelope(**overrides) -> FederatedEnvelope:
    payload = {
        "message_id": "msg-001",
        "sender_node_id": "remote-01",
        "recipient_node_id": "local-01",
        "capability": "research_verified",
        "permission": "submit_work",
        "nonce": "nonce-001",
        "issued_at": NOW - 1,
        "expires_at": NOW + 60,
        "payload": {"task": "verify-source"},
    }
    payload.update(overrides)
    return FederatedEnvelope(**payload)


def test_accepts_valid_signed_envelope(tmp_path: Path) -> None:
    store, authenticator = prepare(tmp_path / "triade.db")
    signed = authenticator.sign(envelope())

    result = store.accept(signed)

    assert result["status"] == "accepted"
    assert result["idempotent"] is False
    assert len(result["payload_sha256"]) == 64
    assert store.get("msg-001")["envelope"]["payload"] == {"task": "verify-source"}


def test_same_message_is_idempotent(tmp_path: Path) -> None:
    store, authenticator = prepare(tmp_path / "triade.db")
    signed = authenticator.sign(envelope())
    store.accept(signed)

    repeated = store.accept(signed)

    assert repeated["status"] == "accepted"
    assert repeated["idempotent"] is True


def test_reused_message_id_with_changed_content_is_rejected(tmp_path: Path) -> None:
    store, authenticator = prepare(tmp_path / "triade.db")
    first = authenticator.sign(envelope())
    store.accept(first)
    changed = authenticator.sign(
        envelope(payload={"task": "different"}, nonce="nonce-002")
    )

    with pytest.raises(ValueError, match="contenido diferente"):
        store.accept(changed)


def test_reused_nonce_is_detected_as_replay(tmp_path: Path) -> None:
    store, authenticator = prepare(tmp_path / "triade.db")
    store.accept(authenticator.sign(envelope()))
    replay = authenticator.sign(envelope(message_id="msg-002"))

    with pytest.raises(ValueError, match="replay detectado"):
        store.accept(replay)


def test_tampered_payload_fails_signature(tmp_path: Path) -> None:
    store, authenticator = prepare(tmp_path / "triade.db")
    signed = authenticator.sign(envelope())
    tampered = replace(signed, payload={"task": "tampered"})

    with pytest.raises(ValueError, match="firma inválida"):
        store.accept(tampered)


def test_expired_future_and_excessive_ttl_are_rejected(tmp_path: Path) -> None:
    store, authenticator = prepare(tmp_path / "triade.db")

    with pytest.raises(ValueError, match="expirado"):
        store.accept(
            authenticator.sign(envelope(message_id="expired", nonce="n-exp", expires_at=NOW - 1))
        )

    with pytest.raises(ValueError, match="emitido en el futuro"):
        store.accept(
            authenticator.sign(
                envelope(
                    message_id="future",
                    nonce="n-future",
                    issued_at=NOW + 11,
                    expires_at=NOW + 20,
                )
            )
        )

    with pytest.raises(ValueError, match="TTL excede"):
        store.accept(
            authenticator.sign(
                envelope(
                    message_id="ttl",
                    nonce="n-ttl",
                    issued_at=NOW,
                    expires_at=NOW + 121,
                )
            )
        )


def test_wrong_recipient_and_unauthorized_scope_are_rejected(tmp_path: Path) -> None:
    store, authenticator = prepare(tmp_path / "triade.db")

    with pytest.raises(ValueError, match="destinatario incorrecto"):
        store.accept(
            authenticator.sign(
                envelope(message_id="wrong", nonce="n-wrong", recipient_node_id="other")
            )
        )

    with pytest.raises(PermissionError, match="no autorizado"):
        store.accept(
            authenticator.sign(
                envelope(message_id="scope", nonce="n-scope", capability="unknown")
            )
        )


def test_quarantined_node_cannot_send(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    store, authenticator = prepare(db_path)
    FederatedNodeRegistry(db_path).transition(
        "remote-01",
        "quarantined",
        actor="safety-monitor",
        reason="comportamiento inválido",
        trust_score=0.2,
    )

    with pytest.raises(PermissionError, match="no autorizado"):
        store.accept(authenticator.sign(envelope()))

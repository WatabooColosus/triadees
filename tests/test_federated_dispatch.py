from pathlib import Path

import pytest

from triade.federation import (
    FederatedDispatcher,
    FederatedEnvelope,
    FederatedNodeIdentity,
    FederatedNodeRegistry,
    FederatedWorkBudget,
    HMACEnvelopeAuthenticator,
)


LOCAL_SECRET = b"local-secret-0123456789abcdef012345"
REMOTE_SECRET = b"remote-secret-0123456789abcdef01234"
NOW = 1_800_000_000.0


def setup_registry(db_path: Path) -> None:
    registry = FederatedNodeRegistry(db_path)
    registry.register(
        FederatedNodeIdentity(
            node_id="remote-01",
            display_name="Remote 01",
            endpoint="https://remote.example.test",
            public_key="REMOTE-PUBLIC-KEY",
            capabilities=("research_verified",),
            permissions=("submit_work", "return_evidence"),
        )
    )
    registry.transition(
        "remote-01",
        "trusted",
        actor="human-operator",
        reason="clave verificada",
        trust_score=0.9,
    )


def authenticator() -> HMACEnvelopeAuthenticator:
    secrets = {"local-01": LOCAL_SECRET, "remote-01": REMOTE_SECRET}
    return HMACEnvelopeAuthenticator(lambda node_id: secrets[node_id])


def budget(**overrides) -> FederatedWorkBudget:
    values = {
        "timeout_seconds": 30.0,
        "cpu_seconds": 10.0,
        "memory_mb": 256,
        "network_kb": 512,
        "output_kb": 64,
    }
    values.update(overrides)
    return FederatedWorkBudget(**values)


def response_for(
    auth: HMACEnvelopeAuthenticator,
    request: FederatedEnvelope,
    *,
    usage=None,
    evidence=None,
    sender="remote-01",
    capability="research_verified",
) -> FederatedEnvelope:
    now = int(NOW)
    return auth.sign(
        FederatedEnvelope(
            message_id=f"job:{request.payload['job_id']}:result",
            sender_node_id=sender,
            recipient_node_id="local-01",
            capability=capability,
            permission="return_evidence",
            nonce=f"job:{request.payload['job_id']}:result",
            issued_at=now,
            expires_at=now + 60,
            payload={
                "kind": "work_result",
                "job_id": request.payload["job_id"],
                "status": "completed",
                "evidence": evidence or {"score": 0.92, "suite": "remote-suite@1"},
                "usage": usage or {
                    "cpu_seconds": 4.0,
                    "memory_mb": 128,
                    "network_kb": 100,
                },
            },
        )
    )


def test_dispatches_and_persists_verified_evidence(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    setup_registry(db_path)
    auth = authenticator()

    def transport(request: FederatedEnvelope, timeout: float) -> FederatedEnvelope:
        assert request.signature
        assert request.payload["budget"]["timeout_seconds"] == timeout
        return response_for(auth, request)

    dispatcher = FederatedDispatcher(
        db_path,
        local_node_id="local-01",
        authenticator=auth,
        transport=transport,
        clock=lambda: NOW,
    )
    result = dispatcher.dispatch(
        "job-001",
        remote_node_id="remote-01",
        capability="research_verified",
        task={"query": "verify source"},
        budget=budget(),
    )

    assert result["status"] == "completed"
    assert result["idempotent"] is False
    assert len(result["result_sha256"]) == 64
    assert len(result["payload"]["result"]["evidence_sha256"]) == 64
    assert result["payload"]["result"]["exchange"]["status"] == "accepted"


def test_same_job_is_idempotent_without_second_transport_call(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    setup_registry(db_path)
    auth = authenticator()
    calls = []

    def transport(request: FederatedEnvelope, timeout: float) -> FederatedEnvelope:
        calls.append(request.message_id)
        return response_for(auth, request)

    dispatcher = FederatedDispatcher(
        db_path,
        local_node_id="local-01",
        authenticator=auth,
        transport=transport,
        clock=lambda: NOW,
    )
    kwargs = dict(
        remote_node_id="remote-01",
        capability="research_verified",
        task={"query": "verify source"},
        budget=budget(),
    )
    dispatcher.dispatch("job-001", **kwargs)
    repeated = dispatcher.dispatch("job-001", **kwargs)

    assert repeated["idempotent"] is True
    assert calls == ["job:job-001:request"]


def test_job_id_cannot_be_reused_with_different_request(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    setup_registry(db_path)
    auth = authenticator()
    dispatcher = FederatedDispatcher(
        db_path,
        local_node_id="local-01",
        authenticator=auth,
        transport=lambda request, timeout: response_for(auth, request),
        clock=lambda: NOW,
    )
    dispatcher.dispatch(
        "job-001",
        remote_node_id="remote-01",
        capability="research_verified",
        task={"query": "one"},
        budget=budget(),
    )

    with pytest.raises(ValueError, match="solicitud diferente"):
        dispatcher.dispatch(
            "job-001",
            remote_node_id="remote-01",
            capability="research_verified",
            task={"query": "two"},
            budget=budget(),
        )


def test_remote_usage_over_budget_marks_job_failed(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    setup_registry(db_path)
    auth = authenticator()

    def transport(request: FederatedEnvelope, timeout: float) -> FederatedEnvelope:
        return response_for(
            auth,
            request,
            usage={"cpu_seconds": 11.0, "memory_mb": 128, "network_kb": 100},
        )

    dispatcher = FederatedDispatcher(
        db_path,
        local_node_id="local-01",
        authenticator=auth,
        transport=transport,
        clock=lambda: NOW,
    )

    with pytest.raises(ValueError, match="cpu_seconds"):
        dispatcher.dispatch(
            "job-over-budget",
            remote_node_id="remote-01",
            capability="research_verified",
            task={"query": "verify"},
            budget=budget(),
        )
    assert dispatcher.get("job-over-budget")["status"] == "failed"


def test_timeout_marks_job_failed(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    setup_registry(db_path)
    auth = authenticator()
    times = iter([NOW, NOW, NOW + 31, NOW + 31])

    dispatcher = FederatedDispatcher(
        db_path,
        local_node_id="local-01",
        authenticator=auth,
        transport=lambda request, timeout: response_for(auth, request),
        clock=lambda: next(times),
    )

    with pytest.raises(TimeoutError, match="timeout"):
        dispatcher.dispatch(
            "job-timeout",
            remote_node_id="remote-01",
            capability="research_verified",
            task={"query": "verify"},
            budget=budget(),
        )
    assert dispatcher.get("job-timeout")["status"] == "failed"


def test_quarantined_or_unauthorized_node_cannot_receive_work(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    setup_registry(db_path)
    auth = authenticator()
    registry = FederatedNodeRegistry(db_path)
    registry.transition(
        "remote-01",
        "quarantined",
        actor="safety-monitor",
        reason="comportamiento inválido",
        trust_score=0.2,
    )
    dispatcher = FederatedDispatcher(
        db_path,
        local_node_id="local-01",
        authenticator=auth,
        transport=lambda request, timeout: response_for(auth, request),
        clock=lambda: NOW,
    )

    with pytest.raises(PermissionError, match="no autorizado"):
        dispatcher.dispatch(
            "job-denied",
            remote_node_id="remote-01",
            capability="research_verified",
            task={"query": "verify"},
            budget=budget(),
        )

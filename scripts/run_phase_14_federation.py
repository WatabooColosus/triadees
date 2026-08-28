#!/usr/bin/env python3
"""Levanta dos procesos HTTP reales y verifica evidencia y revocación."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from triade.federation import (
    FederatedDispatcher,
    FederatedEnvelope,
    FederatedEvidenceGate,
    FederatedNodeIdentity,
    FederatedNodeRegistry,
    FederatedWorkBudget,
    HMACEnvelopeAuthenticator,
)

TRIADE_ENTRYPOINT_KIND = "manual_diagnostic"


def port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request(url: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read())


def _evaluation(evaluation_id: str, score: float) -> dict[str, object]:
    return {
        "evaluation_id": evaluation_id,
        "suite_id": "phase-14-federated-quality",
        "suite_version": "1.0.0",
        "subject_id": evaluation_id,
        "results": [
            {
                "case_id": "quality",
                "score": score,
                "passed": score >= 0.8,
                "actual": score,
                "expected": 1.0,
                "details": {},
            }
        ],
        "aggregate_score": score,
        "created_at": "2026-08-28T00:00:00Z",
        "metadata": {},
    }


def verify_governed_dispatch(db_path: Path) -> dict[str, object]:
    """Despacho firmado → presupuesto → evidencia local → reputación."""
    local_secret = b"phase14-local-secret-0123456789abcdef"
    remote_secret = b"phase14-remote-secret-0123456789abcde"
    secrets = {"local-phase14": local_secret, "remote-phase14": remote_secret}
    auth = HMACEnvelopeAuthenticator(lambda node_id: secrets[node_id])
    registry = FederatedNodeRegistry(db_path)
    registry.register(
        FederatedNodeIdentity(
            node_id="remote-phase14",
            display_name="Remote Phase 14",
            endpoint="https://phase14.invalid",
            public_key="PHASE14-REMOTE-PUBLIC",
            capabilities=("research_verified",),
            permissions=("submit_work", "return_evidence"),
        )
    )
    registry.transition(
        "remote-phase14",
        "trusted",
        actor="phase-14",
        reason="clave efímera verificada dentro del diagnóstico",
        trust_score=0.8,
    )
    evidence = {
        "baseline": _evaluation("baseline", 0.7),
        "candidate": _evaluation("candidate", 0.9),
        "policies": [
            {
                "metric_id": "quality",
                "severity": "high",
                "max_absolute_drop": 0.0,
                "max_relative_drop": 0.0,
                "required": True,
            }
        ],
    }

    def transport(
        envelope: FederatedEnvelope, timeout: float
    ) -> FederatedEnvelope:
        now = int(time.time())
        return auth.sign(
            FederatedEnvelope(
                message_id="job:phase14-governed:result",
                sender_node_id="remote-phase14",
                recipient_node_id="local-phase14",
                capability="research_verified",
                permission="return_evidence",
                nonce="job:phase14-governed:result",
                issued_at=now,
                expires_at=now + max(1, int(timeout)),
                payload={
                    "kind": "work_result",
                    "job_id": envelope.payload["job_id"],
                    "status": "completed",
                    "evidence": evidence,
                    "usage": {
                        "cpu_seconds": 0.1,
                        "memory_mb": 32,
                        "network_kb": 8,
                    },
                },
            )
        )

    dispatch = FederatedDispatcher(
        db_path,
        local_node_id="local-phase14",
        authenticator=auth,
        transport=transport,
    ).dispatch(
        "phase14-governed",
        remote_node_id="remote-phase14",
        capability="research_verified",
        task={"query": "verifica evidencia reproducible"},
        budget=FederatedWorkBudget(
            timeout_seconds=10,
            cpu_seconds=2,
            memory_mb=128,
            network_kb=64,
            output_kb=32,
        ),
    )
    assessment = FederatedEvidenceGate(db_path).assess("phase14-governed")
    return {
        "dispatch_status": dispatch["status"],
        "dispatch_idempotent": dispatch["idempotent"],
        "decision": assessment["decision"],
        "node_state": assessment["node_state"],
        "trust_before": assessment["trust_before"],
        "trust_after": assessment["trust_after"],
        "passed": dispatch["status"] == "completed"
        and assessment["decision"] == "pass"
        and assessment["trust_after"] > assessment["trust_before"],
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        keys = {}
        for name in ("A", "B"):
            private = Ed25519PrivateKey.generate()
            private_path, public_path = root / f"{name}.key", root / f"{name}.pub"
            private_path.write_bytes(
                private.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            public_path.write_bytes(
                private.public_key().public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )
            keys[name] = (private_path, public_path)
        ports = {"A": port(), "B": port()}
        processes = []
        for name, peer in (("A", "B"), ("B", "A")):
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "scripts/federation_real_node.py",
                        "--node-id",
                        f"node-{name}",
                        "--peer-id",
                        f"node-{peer}",
                        "--port",
                        str(ports[name]),
                        "--db",
                        str(root / f"{name}.db"),
                        "--private-key",
                        str(keys[name][0]),
                        "--peer-public-key",
                        str(keys[peer][1]),
                    ]
                )
            )
        try:
            for _ in range(50):
                try:
                    statuses = {
                        name: request(f"http://127.0.0.1:{ports[name]}/")
                        for name in ports
                    }
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("federation_nodes_failed_to_start")
            envelope = request(
                f"http://127.0.0.1:{ports['A']}/produce",
                {
                    "evidence_id": "ev-real-1",
                    "content": "deterministic federation evidence",
                },
            )
            accepted = request(f"http://127.0.0.1:{ports['B']}/accept", envelope)
            duplicate = request(f"http://127.0.0.1:{ports['B']}/accept", envelope)
            revocation = request(
                f"http://127.0.0.1:{ports['A']}/revoke", {"evidence_id": "ev-real-1"}
            )
            revoked = request(f"http://127.0.0.1:{ports['B']}/accept", revocation)
            final = request(f"http://127.0.0.1:{ports['B']}/")
            governed_dispatch = verify_governed_dispatch(root / "governed.db")
            report = {
                "phase": 14,
                "processes": statuses,
                "accepted": accepted,
                "duplicate": duplicate,
                "revocation": revoked,
                "final": final,
                "governed_dispatch": governed_dispatch,
            }
            report["passed"] = (
                statuses["A"]["pid"] != statuses["B"]["pid"]
                and accepted.get("decision") == "accepted"
                and accepted.get("reproduced") is True
                and duplicate.get("idempotent") is True
                and revoked.get("applied") is True
                and final["knowledge"][0]["status"] == "revoked"
                and governed_dispatch["passed"] is True
            )
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                process.wait(timeout=5)
    output = Path("artifacts/triade_verify/phase_14/federation.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

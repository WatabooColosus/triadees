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
            report = {
                "phase": 14,
                "processes": statuses,
                "accepted": accepted,
                "duplicate": duplicate,
                "revocation": revoked,
                "final": final,
            }
            report["passed"] = (
                statuses["A"]["pid"] != statuses["B"]["pid"]
                and accepted.get("decision") == "accepted"
                and accepted.get("reproduced") is True
                and duplicate.get("idempotent") is True
                and revoked.get("applied") is True
                and final["knowledge"][0]["status"] == "revoked"
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

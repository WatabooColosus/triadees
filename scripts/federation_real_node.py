#!/usr/bin/env python3
"""Proceso HTTP mínimo para validar transporte federado real entre nodos."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from triade.federation.exchange import (
    Ed25519EnvelopeAuthenticator,
    FederatedEnvelope,
    FederatedExchangeStore,
)
from triade.federation.registry import FederatedNodeIdentity, FederatedNodeRegistry

TRIADE_ENTRYPOINT_KIND = "manual_diagnostic"


class Node:
    def __init__(
        self, node_id: str, peer_id: str, db: Path, private: Path, peer_public: Path
    ) -> None:
        self.node_id, self.peer_id, self.db = node_id, peer_id, db
        self.private, self.peer_public = private, peer_public
        self.auth = Ed25519EnvelopeAuthenticator(
            lambda _: peer_public.read_bytes(), lambda _: private.read_bytes()
        )
        registry = FederatedNodeRegistry(db)
        registry.register(
            FederatedNodeIdentity(
                node_id=peer_id,
                display_name=peer_id,
                endpoint="http://127.0.0.1",
                public_key=peer_public.read_text(),
                capabilities=("verified_knowledge",),
                permissions=("return_evidence",),
                state="trusted",
                trust_score=0.8,
            )
        )
        self.exchange = FederatedExchangeStore(
            db, local_node_id=node_id, authenticator=self.auth
        )
        with sqlite3.connect(db) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS real_federated_knowledge(
                evidence_id TEXT PRIMARY KEY, content_sha256 TEXT NOT NULL,
                status TEXT NOT NULL, source_node_id TEXT NOT NULL)"""
            )

    def produce(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = int(time.time())
        content = str(payload.get("content") or "")
        evidence_id = str(payload.get("evidence_id") or f"ev-{uuid.uuid4().hex}")
        envelope = FederatedEnvelope(
            message_id=f"msg-{uuid.uuid4().hex}",
            sender_node_id=self.node_id,
            recipient_node_id=self.peer_id,
            capability="verified_knowledge",
            permission="return_evidence",
            nonce=uuid.uuid4().hex,
            issued_at=now,
            expires_at=now + 120,
            payload={
                "kind": "evidence",
                "evidence_id": evidence_id,
                "content": content,
                "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            },
        )
        return self.auth.sign(envelope).to_dict()

    def revoke(self, evidence_id: str) -> dict[str, Any]:
        now = int(time.time())
        envelope = FederatedEnvelope(
            message_id=f"msg-{uuid.uuid4().hex}",
            sender_node_id=self.node_id,
            recipient_node_id=self.peer_id,
            capability="verified_knowledge",
            permission="return_evidence",
            nonce=uuid.uuid4().hex,
            issued_at=now,
            expires_at=now + 120,
            payload={"kind": "revocation", "evidence_id": evidence_id},
        )
        return self.auth.sign(envelope).to_dict()

    def accept(self, payload: dict[str, Any]) -> dict[str, Any]:
        envelope = FederatedEnvelope(**payload)
        accepted = self.exchange.accept(envelope)
        body = envelope.payload
        with sqlite3.connect(self.db) as conn:
            if body.get("kind") == "evidence":
                content = str(body.get("content") or "")
                reproduced = hashlib.sha256(content.encode()).hexdigest()
                if reproduced != body.get("content_sha256"):
                    return {
                        **accepted,
                        "decision": "rejected",
                        "reason": "reproduction_mismatch",
                    }
                conn.execute(
                    "INSERT OR IGNORE INTO real_federated_knowledge VALUES (?, ?, 'accepted', ?)",
                    (body["evidence_id"], reproduced, envelope.sender_node_id),
                )
                return {**accepted, "decision": "accepted", "reproduced": True}
            if body.get("kind") == "revocation":
                changed = conn.execute(
                    "UPDATE real_federated_knowledge SET status='revoked' WHERE evidence_id=?",
                    (body["evidence_id"],),
                ).rowcount
                return {**accepted, "decision": "revoked", "applied": changed == 1}
        return {**accepted, "decision": "rejected", "reason": "unknown_kind"}

    def status(self) -> dict[str, Any]:
        with sqlite3.connect(self.db) as conn:
            rows = conn.execute(
                "SELECT evidence_id,status FROM real_federated_knowledge ORDER BY evidence_id"
            ).fetchall()
        return {
            "node_id": self.node_id,
            "pid": __import__("os").getpid(),
            "knowledge": [{"evidence_id": row[0], "status": row[1]} for row in rows],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--peer-id", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--peer-public-key", required=True)
    args = parser.parse_args()
    node = Node(
        args.node_id,
        args.peer_id,
        Path(args.db),
        Path(args.private_key),
        Path(args.peer_public_key),
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.reply(200, node.status())

        def do_POST(self) -> None:
            try:
                body = json.loads(
                    self.rfile.read(int(self.headers.get("Content-Length", "0")))
                )
                result = (
                    node.produce(body)
                    if self.path == "/produce"
                    else node.revoke(str(body["evidence_id"]))
                    if self.path == "/revoke"
                    else node.accept(body)
                )
                self.reply(200, result)
            except (
                json.JSONDecodeError,
                KeyError,
                OSError,
                ImportError,
                PermissionError,
                sqlite3.Error,
                TypeError,
                ValueError,
            ) as exc:
                self.reply(400, {"error": f"{type(exc).__name__}: {exc}"})

        def reply(self, status: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: object) -> None:
            return

    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

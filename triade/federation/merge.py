"""Authenticated, idempotent federated merge for Tríade Ω.

Enables two real Tríade nodes to merge neurons, learning candidates,
and semantic memory via HMAC-signed requests with duplicate prevention.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class MergeRequest:
    request_id: str
    source_node_id: str
    target_node_id: str
    merge_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "merge_type": self.merge_type,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "signature": self.signature,
        }


@dataclass(slots=True)
class MergeResponse:
    request_id: str
    status: str
    merged_count: int = 0
    conflicts: list[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "status": self.status,
            "merged_count": self.merged_count,
            "conflicts": list(self.conflicts),
            "message": self.message,
        }


class FederatedMerge:
    """HMAC-authenticated, idempotent merge between Tríade nodes."""

    def __init__(
        self,
        node_id: str,
        db_path: str | Path = "triade/memory/triade.db",
        secret_key: str | None = None,
    ) -> None:
        self.node_id = node_id
        self.db_path = Path(db_path)
        self.secret_key = (secret_key or secrets.token_hex(32)).encode("utf-8")
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "memory" / "schemas.sql"
        if schema_path.exists():
            with self._connect() as conn:
                conn.executescript(schema_path.read_text(encoding="utf-8"))

    def _sign(self, data: str) -> str:
        return hmac.new(self.secret_key, data.encode("utf-8"), hashlib.sha256).hexdigest()

    def _payload_bytes(self, request: MergeRequest) -> bytes:
        canonical = json.dumps({
            "request_id": request.request_id,
            "source_node_id": request.source_node_id,
            "target_node_id": request.target_node_id,
            "merge_type": request.merge_type,
            "payload": request.payload,
            "timestamp": request.timestamp,
        }, sort_keys=True, ensure_ascii=False)
        return canonical.encode("utf-8")

    def create_merge_request(
        self,
        target_node_id: str,
        merge_type: str,
        payload: dict[str, Any],
    ) -> MergeRequest:
        now = _utc_now()
        request_id = f"merge-{uuid.uuid4().hex[:12]}"
        request = MergeRequest(
            request_id=request_id,
            source_node_id=self.node_id,
            target_node_id=target_node_id,
            merge_type=merge_type,
            payload=payload,
            timestamp=now,
        )
        request.signature = self._sign(self._payload_bytes(request).decode("utf-8"))
        return request

    def verify_merge_request(self, request: MergeRequest) -> bool:
        expected = self._sign(self._payload_bytes(request).decode("utf-8"))
        return hmac.compare_digest(request.signature, expected)

    def process_merge_request(self, request: MergeRequest) -> MergeResponse:
        if not self.verify_merge_request(request):
            return MergeResponse(request_id=request.request_id, status="rejected", message="Invalid HMAC signature")

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM federated_merge_log WHERE request_id = ?",
                (request.request_id,),
            ).fetchone()
            if existing:
                return MergeResponse(request_id=request.request_id, status="duplicate", message="Request already processed")

        handler = {
            "neurons": self.merge_neurons,
            "learning": self.merge_learning,
            "semantic": self.merge_semantic,
        }.get(request.merge_type)

        if handler is None:
            return MergeResponse(request_id=request.request_id, status="rejected", message=f"Unknown merge type: {request.merge_type}")

        result = handler(request.payload.get("items", []))

        self._log_merge(request, result)

        with self._connect() as conn:
            node_row = conn.execute(
                "SELECT id FROM federated_merge_nodes WHERE node_id = ?",
                (request.source_node_id,),
            ).fetchone()
            if node_row:
                conn.execute(
                    "UPDATE federated_merge_nodes SET last_seen_at = ?, merge_count = merge_count + 1 WHERE node_id = ?",
                    (_utc_now(), request.source_node_id),
                )
            else:
                conn.execute(
                    "INSERT INTO federated_merge_nodes (node_id, last_seen_at, trust_score, merge_count) VALUES (?, ?, 0.5, 1)",
                    (request.source_node_id, _utc_now()),
                )

        return result

    def merge_neurons(self, source_neurons: list[dict[str, Any]]) -> MergeResponse:
        merged = 0
        conflicts: list[str] = []
        with self._connect() as conn:
            for neuron in source_neurons:
                name = neuron.get("name", "")
                if not name:
                    continue
                existing = conn.execute(
                    "SELECT neuron_id FROM neurons WHERE name = ?", (name,)
                ).fetchone()
                if existing:
                    conflicts.append(f"neuron:{name}")
                    continue
                conn.execute(
                    """INSERT INTO neurons (name, domain, status, rules_json, triggers_json, allowed_inputs_json, allowed_outputs_json, forbidden_actions_json, metrics_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        name, neuron.get("domain", "general"), neuron.get("status", "candidate"),
                        json.dumps(neuron.get("rules", []), ensure_ascii=False),
                        json.dumps(neuron.get("triggers", []), ensure_ascii=False),
                        json.dumps(neuron.get("allowed_inputs", []), ensure_ascii=False),
                        json.dumps(neuron.get("allowed_outputs", []), ensure_ascii=False),
                        json.dumps(neuron.get("forbidden_actions", []), ensure_ascii=False),
                        json.dumps(neuron.get("metrics", {}), ensure_ascii=False),
                    ),
                )
                merged += 1
        return MergeResponse(
            request_id="", status="accepted", merged_count=merged, conflicts=conflicts,
            message=f"Merged {merged} neurons, {len(conflicts)} conflicts",
        )

    def merge_learning(self, source_candidates: list[dict[str, Any]]) -> MergeResponse:
        merged = 0
        conflicts: list[str] = []
        with self._connect() as conn:
            for candidate in source_candidates:
                content = candidate.get("content", "")
                content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:32] if content else ""
                existing = conn.execute(
                    "SELECT id FROM learning_queue WHERE content_hash = ?", (content_hash,)
                ).fetchone() if content_hash else None
                if existing:
                    conflicts.append(f"learning:{content_hash}")
                    continue
                conn.execute(
                    """INSERT INTO learning_queue (content, content_hash, source, domain, status, score)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        content, content_hash, candidate.get("source", "federated"),
                        candidate.get("domain", "general"), "candidate", candidate.get("score", 0.5),
                    ),
                )
                merged += 1
        return MergeResponse(
            request_id="", status="accepted", merged_count=merged, conflicts=conflicts,
            message=f"Merged {merged} learning candidates, {len(conflicts)} conflicts",
        )

    def merge_semantic(self, source_docs: list[dict[str, Any]]) -> MergeResponse:
        merged = 0
        conflicts: list[str] = []
        with self._connect() as conn:
            for doc in source_docs:
                key = doc.get("key", "")
                if not key:
                    continue
                existing = conn.execute(
                    "SELECT id FROM semantic_memory WHERE key = ?", (key,)
                ).fetchone()
                if existing:
                    conflicts.append(f"semantic:{key}")
                    continue
                conn.execute(
                    """INSERT INTO semantic_memory (key, value, domain, source_ref, confidence, status)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        key, doc.get("value", ""), doc.get("domain", "general"),
                        doc.get("source_ref", "federated"), doc.get("confidence", 0.5),
                        doc.get("status", "candidate"),
                    ),
                )
                merged += 1
        return MergeResponse(
            request_id="", status="accepted", merged_count=merged, conflicts=conflicts,
            message=f"Merged {merged} semantic docs, {len(conflicts)} conflicts",
        )

    def _log_merge(self, request: MergeRequest, result: MergeResponse) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO federated_merge_log (request_id, source_node, target_node, merge_type, status, merged_count, conflicts_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    request.request_id, request.source_node_id, request.target_node_id,
                    request.merge_type, result.status, result.merged_count,
                    json.dumps(result.conflicts, ensure_ascii=False), _utc_now(),
                ),
            )

    def get_merge_history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM federated_merge_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_merge_stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            by_type = conn.execute(
                "SELECT merge_type, COUNT(*) as c, SUM(merged_count) as total_merged FROM federated_merge_log GROUP BY merge_type"
            ).fetchall()
            by_status = conn.execute(
                "SELECT status, COUNT(*) as c FROM federated_merge_log GROUP BY status"
            ).fetchall()
            node_count = conn.execute("SELECT COUNT(*) as c FROM federated_merge_nodes").fetchone()
        return {
            "by_type": [dict(r) for r in by_type] if by_type else [],
            "by_status": {r["status"]: r["c"] for r in by_status} if by_status else {},
            "known_nodes": node_count["c"] if node_count else 0,
        }

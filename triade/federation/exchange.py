"""Sobres federados autenticados, idempotentes y protegidos contra replay."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .registry import FederatedNodeRegistry

SecretResolver = Callable[[str], bytes]


@dataclass(frozen=True, slots=True)
class FederatedEnvelope:
    message_id: str
    sender_node_id: str
    recipient_node_id: str
    capability: str
    permission: str
    nonce: str
    issued_at: int
    expires_at: int
    payload: dict[str, Any]
    signature: str = ""
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        required = (
            self.message_id,
            self.sender_node_id,
            self.recipient_node_id,
            self.capability,
            self.permission,
            self.nonce,
        )
        if not all(item.strip() for item in required):
            raise ValueError("identificadores, capacidad, permiso y nonce son obligatorios")
        if self.issued_at < 0 or self.expires_at <= self.issued_at:
            raise ValueError("ventana temporal inválida")
        if not isinstance(self.payload, dict):
            raise ValueError("payload debe ser un objeto")

    def unsigned_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("signature", None)
        return payload

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.unsigned_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HMACEnvelopeAuthenticator:
    """Autenticación HMAC-SHA256 con secretos entregados fuera de banda."""

    def __init__(self, secret_resolver: SecretResolver) -> None:
        self.secret_resolver = secret_resolver

    def sign(self, envelope: FederatedEnvelope) -> FederatedEnvelope:
        secret = self._secret(envelope.sender_node_id)
        signature = hmac.new(secret, envelope.canonical_bytes(), hashlib.sha256).hexdigest()
        return FederatedEnvelope(**{**envelope.to_dict(), "signature": signature})

    def verify(self, envelope: FederatedEnvelope) -> bool:
        if len(envelope.signature) != 64:
            return False
        secret = self._secret(envelope.sender_node_id)
        expected = hmac.new(secret, envelope.canonical_bytes(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, envelope.signature)

    def _secret(self, node_id: str) -> bytes:
        secret = self.secret_resolver(node_id)
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError("el secreto de autenticación debe tener al menos 32 bytes")
        return secret


class FederatedExchangeStore:
    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        *,
        local_node_id: str,
        authenticator: HMACEnvelopeAuthenticator,
        clock: Callable[[], float] = time.time,
        max_ttl_seconds: int = 300,
        max_clock_skew_seconds: int = 30,
    ) -> None:
        if not local_node_id.strip():
            raise ValueError("local_node_id es obligatorio")
        if max_ttl_seconds < 1 or max_clock_skew_seconds < 0:
            raise ValueError("límites temporales inválidos")
        self.db_path = Path(db_path)
        self.local_node_id = local_node_id
        self.authenticator = authenticator
        self.clock = clock
        self.max_ttl_seconds = max_ttl_seconds
        self.max_clock_skew_seconds = max_clock_skew_seconds
        self.registry = FederatedNodeRegistry(self.db_path)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS federated_exchanges_v2 (
                    message_id TEXT PRIMARY KEY,
                    sender_node_id TEXT NOT NULL,
                    recipient_node_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    envelope_json TEXT NOT NULL,
                    received_at INTEGER NOT NULL,
                    UNIQUE(sender_node_id, nonce)
                );
                CREATE TABLE IF NOT EXISTS federated_exchange_events_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_federated_exchange_sender
                    ON federated_exchanges_v2(sender_node_id, received_at);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def accept(self, envelope: FederatedEnvelope) -> dict[str, Any]:
        now = int(self.clock())
        self._validate(envelope, now)
        payload_sha = hashlib.sha256(envelope.canonical_bytes()).hexdigest()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT payload_sha256, status FROM federated_exchanges_v2 WHERE message_id = ?",
                (envelope.message_id,),
            ).fetchone()
            if existing is not None:
                if existing["payload_sha256"] != payload_sha:
                    raise ValueError("message_id reutilizado con contenido diferente")
                return {
                    "message_id": envelope.message_id,
                    "status": existing["status"],
                    "idempotent": True,
                    "payload_sha256": payload_sha,
                }
            nonce_exists = conn.execute(
                "SELECT message_id FROM federated_exchanges_v2 WHERE sender_node_id = ? AND nonce = ?",
                (envelope.sender_node_id, envelope.nonce),
            ).fetchone()
            if nonce_exists is not None:
                raise ValueError("replay detectado: nonce ya utilizado")
            conn.execute(
                """INSERT INTO federated_exchanges_v2
                (message_id, sender_node_id, recipient_node_id, nonce, status,
                 payload_sha256, envelope_json, received_at)
                VALUES (?, ?, ?, ?, 'accepted', ?, ?, ?)""",
                (
                    envelope.message_id,
                    envelope.sender_node_id,
                    envelope.recipient_node_id,
                    envelope.nonce,
                    payload_sha,
                    json.dumps(envelope.to_dict(), sort_keys=True),
                    now,
                ),
            )
            self._event(conn, envelope.message_id, "accepted", "validación completa", envelope.to_dict(), now)
        return {
            "message_id": envelope.message_id,
            "status": "accepted",
            "idempotent": False,
            "payload_sha256": payload_sha,
        }

    def get(self, message_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT envelope_json, status, payload_sha256, received_at FROM federated_exchanges_v2 WHERE message_id = ?",
                (message_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "envelope": json.loads(row["envelope_json"]),
            "status": row["status"],
            "payload_sha256": row["payload_sha256"],
            "received_at": row["received_at"],
        }

    def _validate(self, envelope: FederatedEnvelope, now: int) -> None:
        if envelope.recipient_node_id != self.local_node_id:
            raise ValueError("destinatario incorrecto")
        ttl = envelope.expires_at - envelope.issued_at
        if ttl > self.max_ttl_seconds:
            raise ValueError("TTL excede el máximo permitido")
        if envelope.issued_at > now + self.max_clock_skew_seconds:
            raise ValueError("mensaje emitido en el futuro")
        if envelope.expires_at < now:
            raise ValueError("mensaje expirado")
        if not self.registry.authorize(
            envelope.sender_node_id,
            capability=envelope.capability,
            permission=envelope.permission,
        ):
            raise PermissionError("nodo no autorizado para capacidad o permiso")
        if not self.authenticator.verify(envelope):
            raise ValueError("firma inválida")

    @staticmethod
    def _event(
        conn: sqlite3.Connection,
        message_id: str,
        action: str,
        reason: str,
        payload: dict[str, Any],
        now: int,
    ) -> None:
        conn.execute(
            """INSERT INTO federated_exchange_events_v2
            (message_id, action, reason, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)""",
            (message_id, action, reason, json.dumps(payload, sort_keys=True), now),
        )

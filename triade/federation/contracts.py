"""Contratos Pydantic y firma para transporte federado Tríade."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

SANDBOX_TASKS = {
    "echo",
    "sha256",
    "browser_benchmark",
    "preprocess_text",
    "federated_inference_probe",
    "android_model_doctor",
    "android_local_generate",
}


class SignedEnvelope(BaseModel):
    node_id: str = Field(..., min_length=1)
    timestamp: int = Field(..., ge=1)
    nonce: str = Field(..., min_length=8, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    signature: str = Field(..., min_length=16)
    public_key: str | None = None
    signature_alg: Literal["hmac-sha256"] = "hmac-sha256"


class FederatedJobPayload(BaseModel):
    task: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    seconds: float = Field(default=1.0, ge=0.0, le=600.0)


class FederatedJobResultPayload(BaseModel):
    job_id: str = Field(..., min_length=1)
    status: Literal["completed", "failed"] = "completed"
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class FederatedTransportDoctor(BaseModel):
    status: str = "ok"
    mode: str = "signed-federated-http"
    signature_alg: str = "hmac-sha256"
    sandbox_tasks: list[str] = Field(default_factory=lambda: sorted(SANDBOX_TASKS))
    truth: str = "Solo ejecuta tareas sandbox permitidas; no acepta comandos arbitrarios."


def canonical_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def signed_message(node_id: str, timestamp: int, nonce: str, payload: dict[str, Any]) -> str:
    return f"{node_id}.{timestamp}.{nonce}.{canonical_payload(payload)}"


def sign_payload(secret: str, node_id: str, timestamp: int, nonce: str, payload: dict[str, Any]) -> str:
    message = signed_message(node_id=node_id, timestamp=timestamp, nonce=nonce, payload=payload)
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_envelope(envelope: SignedEnvelope, secret: str, max_skew_seconds: int = 300) -> bool:
    now = int(time.time())
    if abs(now - int(envelope.timestamp)) > max_skew_seconds:
        return False
    expected = sign_payload(
        secret=secret,
        node_id=envelope.node_id,
        timestamp=envelope.timestamp,
        nonce=envelope.nonce,
        payload=envelope.payload,
    )
    return hmac.compare_digest(expected, envelope.signature)


def ensure_sandbox_task(task: str) -> str:
    clean = str(task or "").strip()
    if clean not in SANDBOX_TASKS:
        raise ValueError(f"Tarea fuera del sandbox federado: {clean}")
    return clean

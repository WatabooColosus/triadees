"""Despacho federado acotado con presupuesto y evidencia verificable."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .exchange import FederatedEnvelope, FederatedExchangeStore, HMACEnvelopeAuthenticator
from .registry import FederatedNodeRegistry

Transport = Callable[[FederatedEnvelope, float], FederatedEnvelope]


@dataclass(frozen=True, slots=True)
class FederatedWorkBudget:
    timeout_seconds: float
    cpu_seconds: float
    memory_mb: int
    network_kb: int
    output_kb: int

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.cpu_seconds <= 0:
            raise ValueError("timeout_seconds y cpu_seconds deben ser positivos")
        if min(self.memory_mb, self.network_kb, self.output_kb) < 1:
            raise ValueError("memory_mb, network_kb y output_kb deben ser positivos")
        if self.timeout_seconds > 300 or self.cpu_seconds > self.timeout_seconds:
            raise ValueError("presupuesto temporal fuera de límites")
        if self.memory_mb > 4096 or self.network_kb > 10240 or self.output_kb > 1024:
            raise ValueError("presupuesto de recursos fuera de límites")


class FederatedDispatcher:
    """Despacha una tarea por vez y conserva una traza idempotente local."""

    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        *,
        local_node_id: str,
        authenticator: HMACEnvelopeAuthenticator,
        transport: Transport,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.db_path = Path(db_path)
        self.local_node_id = local_node_id
        self.authenticator = authenticator
        self.transport = transport
        self.clock = clock
        self.registry = FederatedNodeRegistry(self.db_path)
        self.incoming = FederatedExchangeStore(
            self.db_path,
            local_node_id=local_node_id,
            authenticator=authenticator,
            clock=clock,
            max_ttl_seconds=300,
        )
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS federated_jobs (
                    job_id TEXT PRIMARY KEY,
                    remote_node_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    result_sha256 TEXT,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS federated_job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_federated_jobs_status
                    ON federated_jobs(status, remote_node_id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def dispatch(
        self,
        job_id: str,
        *,
        remote_node_id: str,
        capability: str,
        task: dict[str, Any],
        budget: FederatedWorkBudget,
    ) -> dict[str, Any]:
        if not all((job_id.strip(), remote_node_id.strip(), capability.strip())):
            raise ValueError("job_id, remote_node_id y capability son obligatorios")
        if not isinstance(task, dict):
            raise ValueError("task debe ser un objeto")
        if not self.registry.authorize(
            remote_node_id,
            capability=capability,
            permission="submit_work",
        ):
            raise PermissionError("nodo remoto no autorizado para ejecutar la capacidad")

        request_payload = {
            "kind": "work_request",
            "job_id": job_id,
            "task": task,
            "budget": asdict(budget),
        }
        request_sha = self._sha(request_payload)
        existing = self.get(job_id)
        if existing is not None:
            if existing["request_sha256"] != request_sha:
                raise ValueError("job_id reutilizado con una solicitud diferente")
            return {**existing, "idempotent": True}

        now = float(self.clock())
        request = self.authenticator.sign(
            FederatedEnvelope(
                message_id=f"job:{job_id}:request",
                sender_node_id=self.local_node_id,
                recipient_node_id=remote_node_id,
                capability=capability,
                permission="submit_work",
                nonce=f"job:{job_id}:request",
                issued_at=int(now),
                expires_at=int(now + budget.timeout_seconds),
                payload=request_payload,
            )
        )
        self._create(job_id, remote_node_id, capability, request_sha, request.to_dict(), now)

        started = float(self.clock())
        try:
            response = self.transport(request, budget.timeout_seconds)
            elapsed = float(self.clock()) - started
            if elapsed > budget.timeout_seconds:
                raise TimeoutError("el nodo remoto excedió el timeout")
            accepted = self.incoming.accept(response)
            result = self._validate_response(job_id, remote_node_id, capability, response, budget)
            result["exchange"] = accepted
            result["elapsed_seconds"] = elapsed
            self._complete(job_id, result)
            return {**self.get(job_id), "idempotent": False}
        except Exception as exc:
            self._fail(job_id, exc)
            raise

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT job_id, remote_node_id, capability, status, request_sha256,
                result_sha256, payload_json, created_at, updated_at
                FROM federated_jobs WHERE job_id = ?""",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "job_id": row["job_id"],
            "remote_node_id": row["remote_node_id"],
            "capability": row["capability"],
            "status": row["status"],
            "request_sha256": row["request_sha256"],
            "result_sha256": row["result_sha256"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _validate_response(
        self,
        job_id: str,
        remote_node_id: str,
        capability: str,
        response: FederatedEnvelope,
        budget: FederatedWorkBudget,
    ) -> dict[str, Any]:
        if response.sender_node_id != remote_node_id:
            raise ValueError("respuesta emitida por un nodo distinto")
        if response.capability != capability or response.permission != "return_evidence":
            raise ValueError("respuesta fuera del alcance autorizado")
        payload = response.payload
        if payload.get("kind") != "work_result" or payload.get("job_id") != job_id:
            raise ValueError("correlación de respuesta inválida")
        if payload.get("status") not in {"completed", "rejected"}:
            raise ValueError("estado remoto inválido")
        evidence = payload.get("evidence")
        usage = payload.get("usage")
        if not isinstance(evidence, dict) or not isinstance(usage, dict):
            raise ValueError("evidence y usage son obligatorios")
        limits = {
            "cpu_seconds": float(budget.cpu_seconds),
            "memory_mb": float(budget.memory_mb),
            "network_kb": float(budget.network_kb),
        }
        for key, limit in limits.items():
            value = float(usage.get(key, -1))
            if value < 0 or value > limit:
                raise ValueError(f"uso remoto excede presupuesto: {key}")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > budget.output_kb * 1024:
            raise ValueError("resultado remoto excede output_kb")
        evidence_sha = self._sha(evidence)
        return {
            "status": payload["status"],
            "evidence": evidence,
            "evidence_sha256": evidence_sha,
            "usage": usage,
            "response_message_id": response.message_id,
        }

    def _create(
        self,
        job_id: str,
        remote_node_id: str,
        capability: str,
        request_sha: str,
        request: dict[str, Any],
        now: float,
    ) -> None:
        payload = {"request": request}
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO federated_jobs
                (job_id, remote_node_id, capability, status, request_sha256,
                 result_sha256, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, 'dispatched', ?, NULL, ?, ?, ?)""",
                (job_id, remote_node_id, capability, request_sha, json.dumps(payload, sort_keys=True), now, now),
            )
            self._event(conn, job_id, "dispatched", payload, now)

    def _complete(self, job_id: str, result: dict[str, Any]) -> None:
        now = float(self.clock())
        result_sha = self._sha(result)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM federated_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            payload = json.loads(row["payload_json"])
            payload["result"] = result
            conn.execute(
                """UPDATE federated_jobs SET status = ?, result_sha256 = ?,
                payload_json = ?, updated_at = ? WHERE job_id = ?""",
                (result["status"], result_sha, json.dumps(payload, sort_keys=True), now, job_id),
            )
            self._event(conn, job_id, result["status"], result, now)

    def _fail(self, job_id: str, exc: Exception) -> None:
        now = float(self.clock())
        error = {"type": type(exc).__name__, "message": str(exc)}
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM federated_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return
            payload = json.loads(row["payload_json"])
            payload["error"] = error
            conn.execute(
                "UPDATE federated_jobs SET status = 'failed', payload_json = ?, updated_at = ? WHERE job_id = ?",
                (json.dumps(payload, sort_keys=True), now, job_id),
            )
            self._event(conn, job_id, "failed", error, now)

    @staticmethod
    def _event(conn: sqlite3.Connection, job_id: str, action: str, payload: dict[str, Any], now: float) -> None:
        conn.execute(
            "INSERT INTO federated_job_events (job_id, action, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (job_id, action, json.dumps(payload, sort_keys=True), now),
        )

    @staticmethod
    def _sha(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

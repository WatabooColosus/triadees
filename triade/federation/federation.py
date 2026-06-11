"""Federación entre nodos autorizados · Tríade Ω Fase D.

Gobierna un registro local de nodos federados y el intercambio controlado de
conocimiento, siguiendo docs/FEDERATION.md.

Principios aplicados:

- Permiso explícito y acceso mínimo: cada intercambio exige un permiso concreto.
- Permisos prohibidos por defecto (no se registran): leer memoria total, escribir
  memoria estable, modificar identidad, ejecutar comandos, acceder a credenciales.
- Trazabilidad: todo intercambio queda en `federated_exchange_log`.
- Revocación posible: un nodo puede pausarse o revocarse.
- Nada recibido se consolida automáticamente: el conocimiento entrante entra al
  Learning Pipeline como CANDIDATO y solo se consolida por la vía humana de Fase C.
- Todo intercambio recibido pasa por Safety antes de registrarse o ingerirse.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from triade.core.contracts import utc_now
from triade.learning.pipeline import LearningPipeline
from triade.models.hardware_profile import HardwareProfiler

TRUST_LEVELS = {"low", "medium", "high"}
NODE_STATUSES = {"active", "paused", "revoked", "archived", "stale"}
EXCHANGE_TYPES = {"knowledge", "pattern", "neuron_spec", "verification", "learning_candidate"}
RISK_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

ALLOWED_PERMISSIONS = {
    "send_knowledge", "receive_knowledge",
    "send_patterns", "receive_patterns",
    "send_neuron_specs", "receive_neuron_specs",
    "request_verification", "request_sandbox_test",
    "publish_capabilities", "request_compute",
}
FORBIDDEN_PERMISSIONS = {
    "read_full_memory", "write_stable_memory", "modify_identity_core",
    "execute_system_commands", "access_private_files", "access_credentials",
}

RECEIVE_PERMISSION = {
    "knowledge": "receive_knowledge",
    "pattern": "receive_patterns",
    "neuron_spec": "receive_neuron_specs",
    "learning_candidate": "receive_knowledge",
    "verification": "request_verification",
}
SEND_PERMISSION = {
    "knowledge": "send_knowledge",
    "pattern": "send_patterns",
    "neuron_spec": "send_neuron_specs",
    "learning_candidate": "send_knowledge",
    "verification": "request_verification",
}
# Marcadores que delatan contenido sensible que no debe salir del nodo local.
PRIVATE_LEAK_FLAGS = ("password", "contraseña", "api_key", "api key", "token", "secreto", "credencial", "private key")


class Federation:
    """Registro de nodos y compuerta de intercambio federado."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db", local_node_id: str = "local") -> None:
        self.db_path = Path(db_path)
        self.schema_path = Path("triade/memory/schemas.sql")
        self.local_node_id = local_node_id
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.learning = LearningPipeline(db_path=self.db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        if not self.schema_path.exists():
            raise FileNotFoundError(f"No existe el esquema de memoria: {self.schema_path}")
        with self._connect() as conn:
            conn.executescript(self.schema_path.read_text(encoding="utf-8"))
            self._ensure_capability_columns(conn)
            self._ensure_exchange_log_columns(conn)
            self._ensure_verification_report_columns(conn)

    @staticmethod
    def _ensure_capability_columns(conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(federated_nodes)").fetchall()}
        additions = {
            "capabilities": "TEXT",
            "capability_status": "TEXT DEFAULT 'unknown'",
            "last_seen_at": "TEXT",
        }
        for name, ddl in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE federated_nodes ADD COLUMN {name} {ddl}")

    @staticmethod
    def _ensure_exchange_log_columns(conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(federated_exchange_log)").fetchall()}
        if "reason" not in columns:
            conn.execute("ALTER TABLE federated_exchange_log ADD COLUMN reason TEXT")

    @staticmethod
    def _ensure_verification_report_columns(conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(verification_reports)").fetchall()}
        if "scope" not in columns:
            conn.execute("ALTER TABLE verification_reports ADD COLUMN scope TEXT")
        if "score" not in columns:
            conn.execute("ALTER TABLE verification_reports ADD COLUMN score REAL")
        if "findings" not in columns:
            conn.execute("ALTER TABLE verification_reports ADD COLUMN findings TEXT")

    # ------------------------------------------------------------------
    # Registro de nodos
    # ------------------------------------------------------------------

    def register_node(
        self,
        node_id: str,
        name: str,
        owner: str | None = None,
        endpoint: str | None = None,
        public_key: str | None = None,
        trust_level: str = "low",
        permissions: list[str] | None = None,
        capabilities: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_id = (node_id or "").strip()
        if not clean_id:
            raise ValueError("node_id es obligatorio.")
        trust = trust_level.strip().lower()
        if trust not in TRUST_LEVELS:
            raise ValueError(f"trust_level inválido: {trust}")

        requested = [str(p).strip() for p in (permissions or []) if str(p).strip()]
        forbidden = sorted(set(requested) & FORBIDDEN_PERMISSIONS)
        if forbidden:
            raise ValueError(f"Permisos prohibidos por defecto, no se pueden otorgar: {forbidden}")
        unknown = sorted(set(requested) - ALLOWED_PERMISSIONS)
        if unknown:
            raise ValueError(f"Permisos no reconocidos: {unknown}")

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO federated_nodes
                (node_id, name, owner, endpoint, public_key, trust_level, permissions, capabilities, capability_status, last_seen_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                ON CONFLICT(node_id) DO UPDATE SET
                    name = excluded.name, owner = excluded.owner, endpoint = excluded.endpoint,
                    public_key = excluded.public_key, trust_level = excluded.trust_level,
                    permissions = excluded.permissions, capabilities = COALESCE(excluded.capabilities, federated_nodes.capabilities),
                    capability_status = COALESCE(excluded.capability_status, federated_nodes.capability_status),
                    last_seen_at = COALESCE(excluded.last_seen_at, federated_nodes.last_seen_at),
                    status = 'active',
                    updated_at = CURRENT_TIMESTAMP""",
                (clean_id, name.strip() or clean_id, owner, endpoint, public_key, trust,
                 json.dumps(sorted(set(requested)), ensure_ascii=False),
                 json.dumps(capabilities, ensure_ascii=False) if capabilities else None,
                 self._capability_status(capabilities),
                 utc_now() if capabilities else None),
            )
        return self.get_node(clean_id) or {}

    def update_capabilities(self, node_id: str, capabilities: dict[str, Any]) -> dict[str, Any]:
        self._require_node(node_id)
        if not isinstance(capabilities, dict) or not capabilities:
            raise ValueError("capabilities debe ser un objeto no vacío.")
        status = self._capability_status(capabilities)
        with self._connect() as conn:
            conn.execute(
                """UPDATE federated_nodes
                SET capabilities = ?, capability_status = ?, last_seen_at = ?, status = 'active', updated_at = CURRENT_TIMESTAMP
                WHERE node_id = ?""",
                (json.dumps(capabilities, ensure_ascii=False), status, utc_now(), node_id),
            )
        return self.get_node(node_id) or {}

    def update_local_capabilities(self, node_id: str) -> dict[str, Any]:
        capabilities = HardwareProfiler().detect().to_dict()
        return self.update_capabilities(node_id, capabilities)

    def set_trust(self, node_id: str, trust_level: str) -> dict[str, Any]:
        trust = trust_level.strip().lower()
        if trust not in TRUST_LEVELS:
            raise ValueError(f"trust_level inválido: {trust}")
        self._require_node(node_id)
        with self._connect() as conn:
            conn.execute("UPDATE federated_nodes SET trust_level = ?, updated_at = CURRENT_TIMESTAMP WHERE node_id = ?",
                         (trust, node_id))
        return self.get_node(node_id) or {}

    def revoke_node(self, node_id: str, reason: str = "") -> dict[str, Any]:
        return self._set_status(node_id, "revoked", reason)

    def pause_node(self, node_id: str, reason: str = "") -> dict[str, Any]:
        return self._set_status(node_id, "paused", reason)

    def reactivate_node(self, node_id: str) -> dict[str, Any]:
        return self._set_status(node_id, "active", "reactivado")

    def stale_node(self, node_id: str, reason: str = "sin heartbeat reciente") -> dict[str, Any]:
        self._require_node(node_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE federated_nodes SET status = 'stale', updated_at = CURRENT_TIMESTAMP WHERE node_id = ?",
                (node_id,),
            )
        return self.get_node(node_id) or {}

    def mark_stale_nodes(self, ttl_seconds: int = 45, keep_node_ids: set[str] | None = None) -> dict[str, Any]:
        keep = keep_node_ids or {"local-pc"}
        now = time.time()
        stale: list[str] = []
        for node in self.list_nodes(status="active"):
            node_id = str(node.get("node_id") or "")
            if node_id in keep:
                continue
            seen_at = self._parse_time(node.get("last_seen_at"))
            if seen_at is None or now - seen_at > ttl_seconds:
                stale.append(node_id)
        for node_id in stale:
            self.stale_node(node_id, f"sin heartbeat en {ttl_seconds}s")
        return {"ttl_seconds": ttl_seconds, "stale_count": len(stale), "stale_nodes": stale}

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM federated_nodes WHERE node_id = ?", (node_id,)).fetchone()
        return self._decode_node(dict(row)) if row else None

    def list_nodes(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if status:
                rows = conn.execute("SELECT * FROM federated_nodes WHERE status = ? ORDER BY id DESC", (status,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM federated_nodes ORDER BY id DESC").fetchall()
        return [self._decode_node(dict(row)) for row in rows]

    def list_capable_nodes(self, min_tier: str | None = None, require_gpu: bool = False) -> list[dict[str, Any]]:
        tier_rank = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
        min_rank = tier_rank.get((min_tier or "low").strip().lower(), 1)
        nodes = []
        for node in self.list_nodes(status="active"):
            capabilities = node.get("capabilities") or {}
            tier = str(capabilities.get("tier") or node.get("capability_status") or "unknown").lower()
            gpus = capabilities.get("gpus") if isinstance(capabilities.get("gpus"), list) else []
            has_gpu = any(float(gpu.get("vram_total_gb") or 0.0) > 0 or bool(gpu.get("cuda_available")) for gpu in gpus if isinstance(gpu, dict))
            if tier_rank.get(tier, 0) < min_rank:
                continue
            if require_gpu and not has_gpu:
                continue
            nodes.append(node)
        return sorted(
            nodes,
            key=lambda node: (
                tier_rank.get(str((node.get("capabilities") or {}).get("tier") or node.get("capability_status") or "unknown").lower(), 0),
                float((node.get("capabilities") or {}).get("ram_available_gb") or 0.0),
                self._max_vram(node.get("capabilities") or {}),
            ),
            reverse=True,
        )

    # ------------------------------------------------------------------
    # Recepción de intercambios (autenticación → permisos → Safety → log → learning)
    # ------------------------------------------------------------------

    def receive_exchange(
        self,
        source_node_id: str,
        exchange_type: str,
        payload: Any,
        risk_level: str = "low",
        title: str | None = None,
        domain: str = "federated",
    ) -> dict[str, Any]:
        exchange_id = f"fed-{uuid4().hex[:16]}"
        clean_type = (exchange_type or "").strip().lower()
        clean_risk = (risk_level or "low").strip().lower()
        content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        payload_ref = hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]

        node = self.get_node(source_node_id)
        required_permission = RECEIVE_PERMISSION.get(clean_type)

        # 1. Autenticación + validación de tipo/permiso/Safety → decisión.
        if node is None:
            decision, safety_status, reason = "blocked", "blocked", "Nodo desconocido."
        elif node["status"] != "active":
            decision, safety_status, reason = "blocked", "blocked", f"Nodo en estado {node['status']}."
        elif clean_type not in EXCHANGE_TYPES:
            decision, safety_status, reason = "blocked", "blocked", f"Tipo de intercambio inválido: {clean_type}."
        elif required_permission not in node["permissions"]:
            decision, safety_status, reason = "blocked", "blocked", f"Permiso requerido ausente: {required_permission}."
        elif clean_risk not in RISK_RANK:
            decision, safety_status, reason = "blocked", "blocked", f"risk_level inválido: {clean_risk}."
        elif clean_risk == "critical":
            decision, safety_status, reason = "blocked", "blocked", "Riesgo crítico: intercambio bloqueado por Safety."
        elif any(flag in content.lower() for flag in PRIVATE_LEAK_FLAGS):
            decision, safety_status, reason = "blocked", "blocked", "Posible fuga de credenciales o memoria privada."
        elif required_permission is None:
            decision, safety_status, reason = "blocked", "blocked", f"Tipo sin permiso configurado: {clean_type}."
        else:
            decision, safety_status, reason = "accepted_as_learning_candidate", "passed", "Intercambio aceptado como candidato."

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO federated_exchange_log
                (exchange_id, source_node_id, exchange_type, payload_ref, risk_level, safety_status, decision, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (exchange_id, source_node_id, clean_type, payload_ref, clean_risk, safety_status, decision, reason),
            )

        learning_candidate = None
        if decision == "accepted_as_learning_candidate" and clean_type in {"knowledge", "learning_candidate", "pattern", "neuron_spec"}:
            learning_candidate = self.learning.ingest(
                title=title or f"Intercambio federado {exchange_id}",
                content=content,
                source_type="node",
                source_ref=source_node_id,
                domain=domain,
                risk_level=clean_risk,
            )
        learning_candidate_id = (learning_candidate or {}).get("candidate_id") if decision == "accepted_as_learning_candidate" else None

        return {
            "exchange_id": exchange_id,
            "decision": decision,
            "safety_status": safety_status,
            "reason": reason,
            "learning_candidate": learning_candidate,
            "consolidated": False,
            "learning_candidate_id": learning_candidate_id,
        }

    # ------------------------------------------------------------------
    # Envío de intercambios
    # ------------------------------------------------------------------

    def send_exchange(
        self,
        source_node_id: str,
        exchange_type: str,
        payload: Any,
        risk_level: str = "low",
    ) -> dict[str, Any]:
        exchange_id = f"fed-{uuid4().hex[:16]}"
        clean_type = (exchange_type or "").strip().lower()
        clean_risk = (risk_level or "low").strip().lower()
        content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        payload_ref = hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]

        node = self.get_node(source_node_id)
        required_permission = SEND_PERMISSION.get(clean_type)

        if node is None:
            decision, safety_status, reason = "blocked", "blocked", "Nodo desconocido."
        elif node["status"] != "active":
            decision, safety_status, reason = "blocked", "blocked", f"Nodo en estado {node['status']}."
        elif clean_type not in EXCHANGE_TYPES:
            decision, safety_status, reason = "blocked", "blocked", f"Tipo de intercambio inválido: {clean_type}."
        elif required_permission not in node["permissions"]:
            decision, safety_status, reason = "blocked", "blocked", f"Permiso requerido ausente: {required_permission}."
        elif any(flag in content.lower() for flag in PRIVATE_LEAK_FLAGS):
            decision, safety_status, reason = "blocked", "blocked", "Posible fuga de credenciales o memoria privada."
        elif required_permission is None:
            decision, safety_status, reason = "blocked", "blocked", f"Tipo sin permiso configurado: {clean_type}."
        else:
            decision, safety_status, reason = "sent", "passed", "Intercambio enviado."

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO federated_exchange_log
                (exchange_id, source_node_id, exchange_type, payload_ref, risk_level, safety_status, decision, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (exchange_id, source_node_id, clean_type, payload_ref, clean_risk, safety_status, decision, reason),
            )

        return {
            "exchange_id": exchange_id,
            "decision": decision,
            "safety_status": safety_status,
            "reason": reason,
        }

    # ------------------------------------------------------------------
    # Doctor (diagnóstico del estado federado)
    # ------------------------------------------------------------------

    def doctor(self) -> dict[str, Any]:
        with self._connect() as conn:
            status_counts: dict[str, int] = {}
            for row in conn.execute("SELECT status, COUNT(*) AS c FROM federated_nodes GROUP BY status").fetchall():
                status_counts[str(row["status"])] = int(row["c"])

            cap_counts: dict[str, int] = {}
            for row in conn.execute("SELECT capability_status, COUNT(*) AS c FROM federated_nodes GROUP BY capability_status").fetchall():
                cap_counts[str(row["capability_status"])] = int(row["c"])

            compute_ready = conn.execute(
                "SELECT COUNT(*) AS c FROM federated_nodes WHERE capability_status = 'high' AND status = 'active'"
            ).fetchone()["c"]

        return {
            "policy": {
                "auto_consolidation": False,
                "identity_core_protected": True,
                "forbidden_permissions": sorted(FORBIDDEN_PERMISSIONS),
            },
            "nodes_by_status": status_counts,
            "nodes_by_capability": cap_counts,
            "compute_ready_nodes": int(compute_ready),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_node(self, node_id: str) -> None:
        if self.get_node(node_id) is None:
            raise ValueError(f"Nodo no registrado: {node_id}")

    def _set_status(self, node_id: str, status: str, reason: str = "") -> dict[str, Any]:
        if status not in NODE_STATUSES:
            raise ValueError(f"status inválido: {status}")
        self._require_node(node_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE federated_nodes SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE node_id = ?",
                (status, node_id),
            )
            if reason:
                conn.execute(
                    """INSERT INTO verification_reports (run_id, scope, status, score, findings, recommendations)
                    VALUES (?, 'federation.node_status', ?, ?, ?, ?)""",
                    (f"node-{node_id}", status, 1.0, f"status={status}; reason={reason}", ""),
                )
        return self.get_node(node_id) or {}

    @staticmethod
    def _decode_node(row: dict[str, Any]) -> dict[str, Any]:
        row["permissions"] = json.loads(row.get("permissions") or "[]")
        row["capabilities"] = json.loads(row.get("capabilities") or "{}")
        return row

    @staticmethod
    def _capability_status(capabilities: dict[str, Any] | None) -> str:
        if not capabilities:
            return "unknown"
        ram = float(capabilities.get("ram_available_gb") or capabilities.get("ram_total_gb") or 0)
        cpu = int(capabilities.get("cpu_count") or 0)
        if ram >= 16 and cpu >= 8:
            return "high"
        if ram >= 8 or cpu >= 4:
            return "medium"
        return "low"

    @staticmethod
    def _parse_time(value: Any) -> float | None:
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            try:
                return datetime.fromisoformat(text.replace(" ", "T") + "+00:00").timestamp()
            except ValueError:
                return None

    @staticmethod
    def _max_vram(capabilities: dict[str, Any]) -> float:
        gpus = capabilities.get("gpus") if isinstance(capabilities.get("gpus"), list) else []
        values = []
        for gpu in gpus:
            if isinstance(gpu, dict):
                values.append(float(gpu.get("vram_total_gb") or 0.0))
        return max(values) if values else 0.0

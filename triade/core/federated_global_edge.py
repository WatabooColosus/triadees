"""Contexto global de borde: estado local + nodos federados autorizados."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.federation.federation import Federation


def build_federated_global_edge_context(
    db_path: str | Path = "triade/memory/triade.db", *, limit: int = 50,
) -> dict[str, Any]:
    """Agrega nodos sin exponer secretos ni convertirlos en autoridad."""
    federation = Federation(db_path=db_path)
    nodes = federation.list_nodes()[: max(1, min(limit, 100))]
    sanitized: list[dict[str, Any]] = []
    for node in nodes:
        caps = node.get("capabilities") if isinstance(node.get("capabilities"), dict) else {}
        sanitized.append({
            "node_id": node.get("node_id"),
            "name": node.get("name"),
            "status": node.get("status"),
            "trust_level": node.get("trust_level"),
            "capability_status": node.get("capability_status"),
            "last_seen_at": node.get("last_seen_at"),
            "permissions": sorted(node.get("permissions") or []),
            "capabilities": {
                "online": bool(caps.get("online")),
                "tier": caps.get("tier"),
                "cpu_count": caps.get("cpu_count"),
                "ram_available_gb": caps.get("ram_available_gb"),
                "gpus": caps.get("gpus") or [],
                "allowed_tasks": caps.get("allowed_tasks") or [],
                "can_run_local_llm": bool(caps.get("can_run_local_llm")),
                "model_runtime_backend": caps.get("model_runtime_backend"),
            },
            "provenance": f"federation_registry:{node.get('node_id')}",
        })
    active = [n for n in sanitized if n["status"] == "active" and n["capabilities"]["online"]]
    return {
        "status": "ok",
        "mode": "federated_global_edge_context",
        "nodes_total": len(sanitized),
        "nodes_active_online": len(active),
        "nodes": sanitized,
        "aggregate": {
            "cpu_count": sum(int(n["capabilities"].get("cpu_count") or 0) for n in active),
            "ram_available_gb": round(sum(float(n["capabilities"].get("ram_available_gb") or 0.0) for n in active), 2),
            "llm_hosts": sum(1 for n in active if n["capabilities"].get("can_run_local_llm")),
        },
        "policy": {
            "bodega_global_is_context_owner": True,
            "central_is_final_decision_owner": True,
            "node_input_is_evidence_not_truth": True,
            "identity_core_write_forbidden": True,
            "stable_memory_write_forbidden": True,
            "credentials_excluded": True,
        },
        "truth": "El borde global reúne señales autorizadas; no delega gobierno ni consolida memoria.",
    }

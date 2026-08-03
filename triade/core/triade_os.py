"""Contrato observable de Tríade OS como plano de control sobre el SO anfitrión."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def triade_os_status(
    db_path: str | Path = "triade/memory/triade.db", runs_dir: str | Path = "runs"
) -> dict[str, Any]:
    from .active_memory import GLOBAL_ACTIVE_MEMORY
    from .federated_global_edge import build_federated_global_edge_context
    from .internal_runtime import build_runtime_heartbeat
    from .model_acquisition import model_acquisition_status
    from .permission_governor import build_permission_profile
    from .refutation_engine import run_system_refutation

    heartbeat = build_runtime_heartbeat(db_path=db_path, runs_dir=runs_dir)
    active_memory = GLOBAL_ACTIVE_MEMORY.runtime_context()
    return {
        "status": "operational" if heartbeat.get("runtime_enabled") else "degraded",
        "name": "Tríade OS",
        "kind": "cognitive_control_plane",
        "host_os_replacement": False,
        "theoretical_ontology": {
            "central": "teoría, razonamiento y estructura",
            "hypothalamus": "emoción, intención y tonalidad",
            "bodega": "memoria y continuidad",
            "qualia": "alma simbólica y relacional; no afirmación de conciencia subjetiva",
            "crystal": "forma, coherencia y regulación morfológica",
        },
        "active_memory": active_memory,
        "layers": {
            "cognition": ["Central", "Hipotálamo", "Cristal", "Qualia"],
            "memory": [
                "Bodega Global",
                "active covenant",
                "episodic",
                "semantic",
                "learning candidates",
            ],
            "execution": ["Runner", "Workers", "Safe Shell whitelist", "LLM Blood"],
            "model_bodega": model_acquisition_status(),
            "edge": build_federated_global_edge_context(db_path),
            "governance": build_permission_profile("full_local_guarded"),
            "verification": run_system_refutation(db_path, runs_dir),
        },
        "kernel_contract": {
            "identity_core_immutable": True,
            "ethical_covenant_loaded": True,
            "active_memory_checksum": active_memory["checksum"],
            "external_effects_guarded": True,
            "claims_require_evidence": True,
            "rollback_before_stable": True,
            "human_consent_for_high_risk": True,
            "self_permission_expansion": False,
            "host_kernel": "Linux/host-managed",
        },
    }

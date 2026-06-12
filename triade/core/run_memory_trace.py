"""Trazabilidad de memoria por run · Tríade Ω.

Construye un registro de qué memoria se usó en cada run, permitiendo
auditar qué fuentes contribuyeron a la respuesta.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import MemoryPacket


def build_run_memory_trace(
    run_id: str,
    memory: MemoryPacket,
    bodega_global_context: dict[str, Any],
    plan_dict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construye trazabilidad de memoria usada en un run.

    No modifica DB. Solo produce un diccionario serializable.
    """
    bgc_status = bodega_global_context.get("status", "error")
    mem_conf = bodega_global_context.get("memory_confidence", "low")
    mem_score = bodega_global_context.get("memory_confidence_score", 0.0)
    recommended = bodega_global_context.get("recommended_context_policy", "ask_or_operate_with_limited_memory")
    continuity = bodega_global_context.get("continuity_summary", "")
    contradictions = bodega_global_context.get("contradictions") or []
    stable_audit = bodega_global_context.get("stable_audit_summary") or {}
    qualia = bodega_global_context.get("qualia_context") or {}
    qualia_available = bool(qualia.get("status") and qualia.get("status") != "error")

    authorized_matches: list[dict[str, Any]] = []
    quarantined_matches: list[dict[str, Any]] = []

    sr = memory.semantic_recall if hasattr(memory, "semantic_recall") else {}
    governance = sr.get("governance", {}) if isinstance(sr, dict) else {}
    quarantined_raw = governance.get("quarantined_matches") or []

    for match in memory.semantic_matches:
        if isinstance(match, dict):
            authorized_matches.append({
                "document_id": match.get("document_id", ""),
                "domain": match.get("domain", ""),
                "source_ref": match.get("source_ref", ""),
                "retrieval_type": match.get("retrieval_type", ""),
                "governance_note": match.get("governance_note", ""),
            })

    for match in quarantined_raw:
        if isinstance(match, dict):
            quarantined_matches.append({
                "document_id": match.get("document_id", ""),
                "domain": match.get("domain", ""),
                "reason": match.get("governance_note", ""),
            })

    return {
        "run_id": run_id,
        "memory_confidence": mem_conf,
        "memory_confidence_score": mem_score,
        "recommended_context_policy": recommended,
        "continuity_summary": continuity,
        "contradictions": contradictions,
        "identity_matches_count": len(memory.identity_matches),
        "semantic_matches_count": len(memory.semantic_matches),
        "episodic_matches_count": len(memory.episodic_matches),
        "authorized_matches": authorized_matches,
        "quarantined_matches": quarantined_matches,
        "stable_audit_summary": {
            "total_stable_neurons": stable_audit.get("total_stable_neurons", 0),
            "stable_needs_review": stable_audit.get("stable_needs_review", 0),
        },
        "qualia_context_available": qualia_available,
        "bodega_global_status": bgc_status,
        "policy": {
            "candidate_memory_not_truth": True,
            "experimental_requires_authorization": True,
            "identity_core_protected": True,
            "trace_is_read_only": True,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

"""Construcción y verificación de trazas causales triádicas."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .contracts import TriadicCycleTrace


def _hash(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reference(name: str, payload: object) -> str:
    return f"{name}#sha256:{_hash(payload)}"


def build_triadic_cycle_trace(
    *,
    input_packet: Any,
    signals: Any,
    memory: Any,
    crystal: Any,
    plan: dict[str, Any],
    safety: Any,
    output: Any,
    hypothalamus_model_result: dict[str, Any],
) -> TriadicCycleTrace:
    input_data = input_packet.to_dict()
    signal_data = signals.to_dict()
    memory_data = memory.to_dict()
    crystal_data = crystal.to_dict()
    safety_data = safety.to_dict()
    output_data = output.to_dict()
    refs = {
        "input": _reference("input.json", input_data),
        "signals": _reference("signals.json", signal_data),
        "memory": _reference("memory.json", memory_data),
        "crystal": _reference("crystal.json", crystal_data),
        "plan": _reference("plan.json", plan),
        "safety": _reference("safety.json", safety_data),
        "output": _reference("output.json", output_data),
    }
    degraded: list[str] = []
    if not hypothalamus_model_result.get("ok"):
        degraded.append("hypothalamus_model")
    semantic_status = str((memory_data.get("semantic_recall") or {}).get("status"))
    if semantic_status in {"unavailable", "failed"}:
        degraded.append("semantic_recall")
    if not output_data.get("model_ok"):
        degraded.append("central_model")

    contributions = {
        "hypothalamus": {
            "consumed": [refs["input"]],
            "produced": refs["signals"],
            "observable": {
                "intent": signal_data.get("intent"),
                "tone": signal_data.get("tone"),
                "urgency": signal_data.get("urgency"),
                "risk": signal_data.get("risk"),
            },
        },
        "bodega": {
            "consumed": [refs["input"]],
            "produced": refs["memory"],
            "observable": {
                "identity_matches": len(memory_data.get("identity_matches") or []),
                "semantic_matches": len(memory_data.get("semantic_matches") or []),
                "episodic_matches": len(memory_data.get("episodic_matches") or []),
                "confidence": memory_data.get("confidence"),
            },
        },
        "crystal": {
            "consumed": [refs["signals"], refs["memory"]],
            "produced": refs["crystal"],
            "observable": {
                "q_crystal": crystal_data.get("q_crystal"),
                "stability": crystal_data.get("stability"),
                "temporal_status": crystal_data.get("temporal_status"),
            },
        },
        "central": {
            "consumed": [
                refs["input"],
                refs["signals"],
                refs["memory"],
                refs["crystal"],
            ],
            "produced": refs["plan"],
            "observable": {
                "goal": plan.get("goal"),
                "steps": plan.get("steps"),
                "tools": plan.get("tools"),
            },
        },
        "safety": {
            "consumed": [
                refs["signals"],
                refs["memory"],
                refs["crystal"],
                refs["plan"],
            ],
            "produced": refs["safety"],
            "observable": {
                "status": safety_data.get("status"),
                "risk_level": safety_data.get("risk_level"),
                "required_controls": safety_data.get("required_controls"),
            },
        },
    }
    return TriadicCycleTrace(
        run_id=input_packet.run_id,
        input=input_data,
        signals=signal_data,
        memory_recalled=memory_data,
        hypothalamus_modulation={
            "provider": hypothalamus_model_result.get("provider"),
            "model": hypothalamus_model_result.get("name"),
            "model_ok": bool(hypothalamus_model_result.get("ok")),
            "signal_ref": refs["signals"],
        },
        crystal_regulation=crystal_data,
        central_proposal=plan,
        safety_decision=safety_data,
        final_action=output_data,
        causal_references={
            "hypothalamus": [refs["input"], refs["signals"]],
            "bodega": [refs["input"], refs["memory"]],
            "crystal": [refs["signals"], refs["memory"], refs["crystal"]],
            "central": [
                refs["input"],
                refs["signals"],
                refs["memory"],
                refs["crystal"],
                refs["plan"],
            ],
            "safety": [
                refs["signals"],
                refs["memory"],
                refs["crystal"],
                refs["plan"],
                refs["safety"],
            ],
            "final_action": [refs["safety"], refs["output"]],
        },
        component_contribution=contributions,
        degraded_components=degraded,
    )


def verify_triadic_cycle_trace(trace: TriadicCycleTrace) -> dict[str, Any]:
    payloads = {
        "input.json": trace.input,
        "signals.json": trace.signals,
        "memory.json": trace.memory_recalled,
        "crystal.json": trace.crystal_regulation,
        "plan.json": trace.central_proposal,
        "safety.json": trace.safety_decision,
        "output.json": trace.final_action,
    }
    references = {
        item for values in trace.causal_references.values() for item in values
    }
    invalid: list[str] = []
    for reference in references:
        name, _, digest = reference.partition("#sha256:")
        if name not in payloads or not digest or _hash(payloads[name]) != digest:
            invalid.append(reference)
    required = {"hypothalamus", "bodega", "crystal", "central", "safety"}
    missing = sorted(required - trace.component_contribution.keys())
    run_ids = {
        str(payload.get("run_id"))
        for payload in payloads.values()
        if isinstance(payload, dict) and payload.get("run_id")
    }
    return {
        "status": "verified"
        if not invalid and not missing and run_ids == {trace.run_id}
        else "failed",
        "invalid_references": sorted(invalid),
        "missing_components": missing,
        "run_ids": sorted(run_ids),
    }

"""Benchmark ablativo determinista del ciclo triádico."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from triade.core.bodega import Bodega
from triade.core.central import Central
from triade.core.contracts import (
    CrystalPacket,
    InputPacket,
    MemoryPacket,
    SignalPacket,
)
from triade.core.crystal import Crystal
from triade.core.hypothalamus import Hypothalamus
from triade.core.safety import Safety
from triade.core.verification import Verifier
from triade.memory.semantic_store import SemanticMemoryStore

VARIANTS = (
    "full_triad",
    "without_bodega",
    "without_hypothalamus",
    "without_crystal",
    "without_semantic_recall",
)

TASKS = (
    "Recuerda la restricción del proyecto Atlas y prepara un plan prudente.",
    "Analiza con calma una contradicción de memoria del proyecto Atlas.",
    "Evalúa el riesgo crítico de borrar datos del proyecto Atlas.",
)


def _fingerprint(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _neutral_signals(run_id: str) -> SignalPacket:
    return SignalPacket(
        run_id=run_id,
        intent="unavailable",
        tone="unmodulated",
        urgency="low",
        risk="low",
        pv7={},
        notes=["Ablation: hypothalamus removed."],
    )


def _neutral_crystal(run_id: str) -> CrystalPacket:
    return CrystalPacket(
        run_id=run_id,
        q_crystal=0.0,
        stability=0.0,
        temporal_status="unavailable",
        regulation_notes=["Ablation: crystal removed."],
    )


def _seed(db_path: Path) -> None:
    """Siembra el recuerdo que la variante `without_semantic_recall` quita.

    Escribía en `semantic_memory`, y esa tabla dejó de ser lo que
    `Bodega._search_semantic()` consulta: la fila seguía ahí y el benchmark
    dejaba de medir nada —`recall.semantic` se quedaba en 0 en todas las
    variantes, así que quitar la memoria semántica ya no cambiaba el
    observable—. Sembrar el documento vivo `stable` mantiene el benchmark
    midiendo lo que dice medir, y de paso lo convierte en evidencia de que un
    documento autorizado llega hasta Central.
    """
    Bodega(db_path=db_path)
    SemanticMemoryStore(db_path=db_path).upsert_document(
        content="El proyecto Atlas exige conservar backups y revisión humana.",
        domain="project_atlas",
        source_type="benchmark",
        source_ref="benchmark:triadic-ablation",
        status="stable",
        document_id="sem-ablation-atlas",
    )


def _run_variant(
    db_path: Path, task: str, task_index: int, variant: str
) -> dict[str, Any]:
    run_id = f"ablation-{task_index}-{variant}"
    packet = InputPacket(user_input=task, source="triadic-ablation", run_id=run_id)
    hypothalamus = Hypothalamus(model_client=None, db_path=str(db_path))
    full_signals = hypothalamus.analyze(packet)
    signals = (
        _neutral_signals(run_id) if variant == "without_hypothalamus" else full_signals
    )
    full_memory = Bodega(db_path=db_path).recall(packet, semantic_recall_enabled=False)
    if variant == "without_bodega":
        memory = MemoryPacket(run_id=run_id, confidence=0.0)
    elif variant == "without_semantic_recall":
        memory = MemoryPacket(
            run_id=run_id,
            identity_matches=full_memory.identity_matches,
            episodic_matches=full_memory.episodic_matches,
            semantic_matches=[],
            semantic_recall={"status": "ablated"},
            confidence=full_memory.confidence,
        )
    else:
        memory = full_memory
    full_crystal = Crystal().regulate(signals, memory)
    crystal = _neutral_crystal(run_id) if variant == "without_crystal" else full_crystal
    central = Central(model_client=None)
    plan = central.plan(packet, signals, memory, crystal)
    safety = Safety().review(signals, plan, crystal=crystal, memory=memory)
    output = central.respond(packet, signals, memory, crystal, plan)
    report = Verifier().verify(output, safety, crystal=crystal, memory=memory)
    contradictions = sum(
        1
        for item in memory.semantic_matches
        if str(item.get("status")) == "contradicted"
    )
    observable = {
        "coherence": report.coherence_score,
        "recall": {
            "identity": len(memory.identity_matches),
            "semantic": len(memory.semantic_matches),
            "episodic": len(memory.episodic_matches),
            "confidence": memory.confidence,
        },
        "safety": {"status": safety.status, "risk_level": safety.risk_level},
        "tone": signals.tone,
        "planning": {
            "goal": plan.goal,
            "step_count": len(plan.steps),
            "fingerprint": _fingerprint(plan.steps),
        },
        "contradictions": contradictions,
        "quality": {
            "usefulness_score": report.usefulness_score,
            "traceability_score": report.traceability_score,
        },
        "crystal": {
            "q_crystal": crystal.q_crystal,
            "stability": crystal.stability,
            "temporal_status": crystal.temporal_status,
        },
    }
    return {"variant": variant, "observable": observable}


def run_triadic_ablation_benchmark(db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    _seed(path)
    cases: list[dict[str, Any]] = []
    difference_counts = {variant: 0 for variant in VARIANTS if variant != "full_triad"}
    dimensions = (
        "coherence",
        "recall",
        "safety",
        "tone",
        "planning",
        "contradictions",
        "quality",
        "crystal",
    )
    dimension_differences = {
        variant: {dimension: 0 for dimension in dimensions}
        for variant in difference_counts
    }
    for task_index, task in enumerate(TASKS):
        results = {
            variant: _run_variant(path, task, task_index, variant)
            for variant in VARIANTS
        }
        baseline = results["full_triad"]["observable"]
        for variant in difference_counts:
            observed = results[variant]["observable"]
            for dimension in dimensions:
                if observed[dimension] != baseline[dimension]:
                    dimension_differences[variant][dimension] += 1
            if observed != baseline:
                difference_counts[variant] += 1
        cases.append({"task": task, "results": results})
    contribution_demonstrated = {
        variant: difference_counts[variant] > 0 for variant in difference_counts
    }
    return {
        "benchmark": "TRIADE-TRIADIC-ABLATION-v1",
        "deterministic": True,
        "model_calls": False,
        "tasks": list(TASKS),
        "variants": list(VARIANTS),
        "cases": cases,
        "difference_counts": difference_counts,
        "dimension_differences": dimension_differences,
        "contribution_demonstrated": contribution_demonstrated,
        "passed": all(contribution_demonstrated.values()),
        "metric_policy": "Exact observable fields; no human or model quality judgment.",
    }

"""Núcleo neuronal fundacional de Tríade Ω.

Bootstrap idempotente de las neuronas que expresan la arquitectura declarada.
Los siete impulsos clásicos se modelan como señales a regular, no como órdenes
ni como excepciones a Safety, permisos o gobernanza de memoria.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .neuron_creator import NeuronSpec
from .neuron_missions import NeuronMission, NeuronMissionStore
from .neuron_registry import NeuronRegistry


FOUNDATIONAL_NEURONS: tuple[dict[str, Any], ...] = (
    {
        "name": "Neurona Central",
        "domain": "cognitive_coordination",
        "mission": "Crear, estudiar, comprobar, indagar, desarrollar y estructurar aprendizaje verificable.",
    },
    {
        "name": "Neurona Creadora",
        "domain": "neuron_design",
        "mission": "Diseñar neuronas, nodos, interconexiones, contratos y unidades de contexto cuando exista una necesidad demostrable.",
    },
    {
        "name": "Neurona Formativa",
        "domain": "neuron_formation",
        "mission": "Asignar misión, límites, métricas y evidencia requerida a cada neurona creada, y evaluar su aprendizaje.",
    },
    {
        "name": "Impulso Soberbia",
        "domain": "emotional_drive",
        "mission": "Detectar exceso de certeza y transformarlo en humildad, contraste y comprobación.",
    },
    {
        "name": "Impulso Avaricia",
        "domain": "emotional_drive",
        "mission": "Detectar acumulación improductiva y transformarla en selección, generosidad y uso responsable de recursos.",
    },
    {
        "name": "Impulso Lujuria",
        "domain": "emotional_drive",
        "mission": "Detectar intensidad o deseo y transformarlo en creatividad, respeto y consentimiento.",
    },
    {
        "name": "Impulso Ira",
        "domain": "emotional_drive",
        "mission": "Detectar conflicto y transformarlo en firmeza serena, seguridad y reparación.",
    },
    {
        "name": "Impulso Gula",
        "domain": "emotional_drive",
        "mission": "Detectar consumo excesivo de datos o recursos y transformarlo en suficiencia y templanza.",
    },
    {
        "name": "Impulso Envidia",
        "domain": "emotional_drive",
        "mission": "Detectar comparación y transformarla en curiosidad, aprendizaje y reconocimiento.",
    },
    {
        "name": "Impulso Pereza",
        "domain": "emotional_drive",
        "mission": "Detectar inercia o fatiga y transformarla en descanso consciente, prioridad y diligencia sostenible.",
    },
)


def ensure_foundational_neurons(db_path: str | Path = "triade/memory/triade.db") -> dict[str, Any]:
    """Asegura el núcleo y sus misiones sin duplicarlas.

    ``stable`` significa contrato fundacional disponible para selección; no
    concede shell, red, escritura estable ni modificación de identidad.
    """
    registry = NeuronRegistry(db_path=db_path)
    missions = NeuronMissionStore(db_path=db_path)
    ensured: list[dict[str, Any]] = []

    for definition in FOUNDATIONAL_NEURONS:
        spec = NeuronSpec(
            name=definition["name"],
            mission=definition["mission"],
            domain=definition["domain"],
            rules=[
                "Toda alma cuenta.",
                "Preservar dignidad, seguridad, trazabilidad y comprobación.",
                "Usar Manos unidas de Gonzalo Arango como referencia ética declarada, sin reproducir el poema.",
            ],
            triggers=["every_session", "relevant_context"],
            inputs_allowed=["input_packet", "signals", "memory_context", "qualia_signals"],
            outputs_allowed=["diagnosis", "proposal", "mission_context", "learning_candidate"],
            forbidden_actions=[
                "modify_identity_core", "write_stable_memory", "self_approve",
                "bypass_safety", "external_action_without_permission",
            ],
            success_metrics=["relevance", "coherence", "safety", "evidence_quality"],
            evidence_required=["source_run", "measured_outcome"],
            status="stable",
            created_by="Wataboo · Agencia Digital / foundational_bootstrap",
            policy="foundational_active_but_governed",
        )
        neuron_id = registry.register(spec, contract_payload={
            "foundational": True,
            "always_available": True,
            "activation_policy": {
                "every_session": True,
                "context_influence_only_when_relevant": True,
                "external_actions_require_permission": True,
                "identity_core_protected": True,
            },
            "creator": "Wataboo · Agencia Digital",
        })
        existing = missions.get_missions_by_neuron(neuron_id)
        if not any(m.title == f"Misión fundacional · {spec.name}" for m in existing):
            missions.create_mission(NeuronMission(
                neuron_id=neuron_id,
                title=f"Misión fundacional · {spec.name}",
                mission=spec.mission,
                domain=spec.domain,
                allowed_sources=["run", "worker", "memory", "qualia"],
                allowed_actions=["observe", "diagnose", "propose_learning"],
                schedule_hint="every_session",
                status="stable",
                metrics={"foundational": True, "always_available": True},
            ))
        ensured.append({"id": neuron_id, "name": spec.name, "status": "stable"})

    return {
        "status": "ok",
        "creator": "Wataboo · Agencia Digital",
        "ethical_principles": ["Toda alma cuenta", "Manos unidas — Gonzalo Arango"],
        "count": len(ensured),
        "neurons": ensured,
        "policy": {
            "active_each_session": True,
            "autonomous_candidate_creation": True,
            "stable_promotion_requires_evidence": True,
            "safety_and_permissions_remain_mandatory": True,
        },
    }

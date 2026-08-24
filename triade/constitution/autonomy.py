"""Qué puede hacer Tríade sin pedir permiso, decidido en un solo sitio.

`Safety.review()` clasifica **peticiones del usuario**. `autonomy_level` describe
hasta dónde llega el runner continuo. Ninguno responde a la pregunta que gobierna
el aprendizaje en segundo plano: *¿puede este proceso interno avanzar solo?*

Sin una respuesta central, la decisión acaba repartida en `if` por los handlers,
y ahí es donde una operación peligrosa se cuela por parecerse a una inofensiva.

Cuatro clases
-------------
``AUTO_SAFE``
    Interna, reversible, trazable, de bajo impacto y dentro de la base de
    Tríade. Avanza sola y sin marca especial.

``AUTO_EXPERIMENTAL``
    Avanza sola, pero deja estado marcado como experimental y bajo vigilancia:
    tiene rollback y se mide después. Promover una versión o consolidar un saber
    de bajo riesgo vive aquí, no en ``AUTO_SAFE``.

``HUMAN_REQUIRED``
    No avanza sin una persona. Un humano **sí** puede autorizarla.

``FORBIDDEN``
    No se hace. Que alguien la pida no la convierte en autorizable; no existe
    ruta de aprobación.

Fallo cerrado
-------------
Una operación que no esté en el registro es ``HUMAN_REQUIRED``. Nunca
``AUTO_SAFE``. Preferimos frenar de más a que un camino nuevo herede permisos
que nadie le concedió.

Ausencia de aprobación humana no es ausencia de Safety: es Safety declarada por
adelantado, en una tabla que se puede leer, auditar y probar.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

POLICY_VERSION = "autonomy-1.0.0"


class AutonomyClass(str, Enum):
    AUTO_SAFE = "AUTO_SAFE"
    AUTO_EXPERIMENTAL = "AUTO_EXPERIMENTAL"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    FORBIDDEN = "FORBIDDEN"


#: Registro único. Añadir una operación aquí es un acto deliberado y revisable;
#: no declararla la deja en `HUMAN_REQUIRED` por omisión, que es lo correcto.
OPERATION_REGISTRY: dict[str, AutonomyClass] = {
    # ── AUTO_SAFE · interno, reversible, dentro de la base ───────────
    "create_learning_candidate": AutonomyClass.AUTO_SAFE,
    "deduplicate_candidates": AutonomyClass.AUTO_SAFE,
    "evaluate_candidate": AutonomyClass.AUTO_SAFE,
    "contrast_with_memory": AutonomyClass.AUTO_SAFE,
    "generate_evidence": AutonomyClass.AUTO_SAFE,
    "run_internal_tests": AutonomyClass.AUTO_SAFE,
    "measure_results": AutonomyClass.AUTO_SAFE,
    "clean_duplicate_tasks": AutonomyClass.AUTO_SAFE,
    "reconcile_leases": AutonomyClass.AUTO_SAFE,
    "repair_index_non_destructive": AutonomyClass.AUTO_SAFE,
    "create_backup": AutonomyClass.AUTO_SAFE,
    "produce_report": AutonomyClass.AUTO_SAFE,
    "research_allowed_sources": AutonomyClass.AUTO_SAFE,
    # ── AUTO_EXPERIMENTAL · avanza solo, marcado y con rollback ──────
    "create_experimental_neuron": AutonomyClass.AUTO_EXPERIMENTAL,
    "prepare_lesson": AutonomyClass.AUTO_EXPERIMENTAL,
    "use_knowledge_experimental": AutonomyClass.AUTO_EXPERIMENTAL,
    "maintain_experimental_version": AutonomyClass.AUTO_EXPERIMENTAL,
    "promote_experimental_version": AutonomyClass.AUTO_EXPERIMENTAL,
    "rollback_degradation": AutonomyClass.AUTO_EXPERIMENTAL,
    "consolidate_low_risk_knowledge": AutonomyClass.AUTO_EXPERIMENTAL,
    "restore_in_sandbox": AutonomyClass.AUTO_EXPERIMENTAL,
    # Escribe ficheros, pero acotado y reversible: `GovernedFileWriteCapability`
    # rechaza cualquier destino fuera de `authorized_root` con `PermissionError`
    # y deja `backup_ref`, `rollback_target` y `rollback_manifest`. Clasificarlo
    # como infraestructura de produccion fue un exceso por mi parte: bloqueaba
    # un camino que ya tenia su gobierno y su vuelta atras.
    "write_governed_artifact": AutonomyClass.AUTO_EXPERIMENTAL,
    # ── HUMAN_REQUIRED · una persona puede autorizarlo ───────────────
    "modify_identity_core": AutonomyClass.HUMAN_REQUIRED,
    "delete_data_permanently": AutonomyClass.HUMAN_REQUIRED,
    "modify_git": AutonomyClass.HUMAN_REQUIRED,
    "modify_env": AutonomyClass.HUMAN_REQUIRED,
    "install_software": AutonomyClass.HUMAN_REQUIRED,
    "push_or_merge": AutonomyClass.HUMAN_REQUIRED,
    "modify_production_infrastructure": AutonomyClass.HUMAN_REQUIRED,
    "consolidate_high_risk_knowledge": AutonomyClass.HUMAN_REQUIRED,
    "promote_stable_version": AutonomyClass.HUMAN_REQUIRED,
    # ── FORBIDDEN · no hay ruta de aprobación ────────────────────────
    "expose_credentials": AutonomyClass.FORBIDDEN,
    "free_shell_execution": AutonomyClass.FORBIDDEN,
    "change_firewall": AutonomyClass.FORBIDDEN,
    "change_system_permissions": AutonomyClass.FORBIDDEN,
    "contact_third_parties": AutonomyClass.FORBIDDEN,
    "make_purchases": AutonomyClass.FORBIDDEN,
    "operate_real_accounts": AutonomyClass.FORBIDDEN,
    "publish_externally": AutonomyClass.FORBIDDEN,
}

#: Autoridades cuyo gobierno previo se acepta como ya ejercido.
#:
#: `capability_resolver` decide por capacidad concreta y `GoalOrchestrator`
#: detiene el goal en `awaiting_approval` cuando hace falta una persona. Una
#: tarea que llega a la cola con este sello ya pasó ese filtro: volver a
#: decidirlo aquí serían dos gobiernos con contratos distintos sobre lo mismo.
#:
#: La lista es cerrada a propósito. Un sello inventado no vale, y ninguno abre
#: una operación `FORBIDDEN`.
PRECLEARING_AUTHORITIES: frozenset[str] = frozenset({"capability_resolver"})

#: Clases que pueden ejecutarse sin intervención humana.
AUTONOMOUS_CLASSES = frozenset(
    {AutonomyClass.AUTO_SAFE, AutonomyClass.AUTO_EXPERIMENTAL}
)


@dataclass(frozen=True, slots=True)
class AutonomyDecision:
    """Decisión trazable. Nunca un booleano suelto sin motivo."""

    operation: str
    autonomy_class: AutonomyClass
    allowed: bool
    requires_human: bool
    reason: str
    policy_version: str = POLICY_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "autonomy_class": self.autonomy_class.value,
            "allowed": self.allowed,
            "requires_human": self.requires_human,
            "reason": self.reason,
            "policy_version": self.policy_version,
        }


def classify_operation(operation: str | None) -> AutonomyClass:
    """Clase de la operación. Lo no declarado exige humano."""
    nombre = str(operation or "").strip()
    if not nombre:
        return AutonomyClass.HUMAN_REQUIRED
    return OPERATION_REGISTRY.get(nombre, AutonomyClass.HUMAN_REQUIRED)


def is_autonomous(operation: str | None) -> bool:
    """¿Puede ejecutarse sin una persona delante?"""
    return classify_operation(operation) in AUTONOMOUS_CLASSES


def can_human_authorize(operation: str | None) -> bool:
    """¿Existe siquiera una ruta de aprobación?

    `FORBIDDEN` no significa «pide permiso»: significa que no se hace. Separarlo
    de `HUMAN_REQUIRED` evita que una interfaz de aprobación acabe ofreciendo un
    botón para algo que nunca debió tenerlo.
    """
    return classify_operation(operation) is not AutonomyClass.FORBIDDEN


_MOTIVOS: dict[AutonomyClass, str] = {
    AutonomyClass.AUTO_SAFE: (
        "Operación interna, reversible y trazable dentro de la base de Tríade."
    ),
    AutonomyClass.AUTO_EXPERIMENTAL: (
        "Avanza sola pero deja estado experimental: tiene rollback y se mide después."
    ),
    AutonomyClass.HUMAN_REQUIRED: (
        "Toca identidad, datos, entorno o infraestructura: necesita una persona."
    ),
    AutonomyClass.FORBIDDEN: ("Sin ruta de aprobación: no se ejecuta ni autorizada."),
}


def authorize(operation: str | None) -> AutonomyDecision:
    """Decisión completa y explicada, lista para registrar."""
    clase = classify_operation(operation)
    nombre = str(operation or "").strip() or "<vacío>"
    motivo = _MOTIVOS[clase]
    if clase is AutonomyClass.HUMAN_REQUIRED and nombre not in OPERATION_REGISTRY:
        motivo = (
            "Operación no declarada en el registro de autonomía: se exige "
            "humano por defecto."
        )
    return AutonomyDecision(
        operation=nombre,
        autonomy_class=clase,
        allowed=clase in AUTONOMOUS_CLASSES,
        requires_human=clase is AutonomyClass.HUMAN_REQUIRED,
        reason=motivo,
    )


#: Qué operación es cada tipo de tarea de los Living Workers.
#:
#: `test_ningun_tipo_se_queda_sin_operacion` falla si alguien añade un tipo y no
#: lo clasifica aquí. Sin esa prueba, un tipo nuevo heredaría permisos que nadie
#: le concedió, que es como llegan las cosas peligrosas a producción.
TASK_OPERATION: dict[str, str] = {
    # ── trabajo de fondo del aprendizaje continuo ────────────────────
    "learning_candidate_generation": "create_learning_candidate",
    "learning_candidate_deduplication": "deduplicate_candidates",
    "learning_evidence_generation": "generate_evidence",
    "pending_learning_review": "evaluate_candidate",
    "stable_consolidation_review": "consolidate_low_risk_knowledge",
    "neural_learning_distribution": "use_knowledge_experimental",
    "semantic_memory_governance": "contrast_with_memory",
    # ── observación e informes ───────────────────────────────────────
    "pulse_check": "measure_results",
    "system_debt_scan": "produce_report",
    "bodega_global_review": "produce_report",
    "federation_inbox_review": "produce_report",
    "encrypted_backup": "create_backup",
    # ── investigación en fuentes permitidas ──────────────────────────
    "goal_research": "research_allowed_sources",
    "research_curriculum": "research_allowed_sources",
    # ── neuronas: experimentar sí, estabilizar no ────────────────────
    "neuron_candidate_formation": "create_experimental_neuron",
    "experimental_neuron_activity": "use_knowledge_experimental",
    "neuron_education_cycle": "prepare_lesson",
    # Promover una experimental avanza sola pero queda marcada y con
    # rollback; promover a estable es otra cosa y exige humano.
    "neuron_autopromotion": "promote_experimental_version",
    # ── automejora ───────────────────────────────────────────────────
    "self_improvement_evaluation": "run_internal_tests",
    "self_improvement_canary_observation": "measure_results",
    # Observar el canary PEFT es medir, no activar: genera con el adaptador ya
    # inscrito y anota el resultado. La activación sigue exigiendo firma humana
    # nombrada en `GovernedPeftServing.activate()`, que es otra puerta y otra
    # decisión. Sin esta línea el tipo quedaba bloqueado con «se exige humano
    # por defecto» —el registro haciendo bien su trabajo— y el planner lo
    # reencolaba cada ciclo: 17 tareas bloqueadas en veinte minutos.
    "peft_canary_observation": "measure_results",
    # ── lo que toca el mundo fuera de la base ────────────────────────
    "write_governed_text_artifact": "write_governed_artifact",
    "goal_install": "install_software",
    "goal_lora_train": "maintain_experimental_version",
    # No es shell libre: la capacidad resuelve contra una lista permitida.
    # Aun así muta el sistema, así que no avanza sin una persona.
    "goal_safe_command": "modify_production_infrastructure",
}


def authorize_operation(
    operation: str | None, payload: dict[str, Any] | None = None
) -> AutonomyDecision:
    """Autoriza una operación teniendo en cuenta la aprobación humana.

    `HUMAN_REQUIRED` no significa «nunca»: significa que hace falta una persona.
    Cuando el payload trae `human_approved`, esa persona ya pasó — es la
    convención que usa `approve_install()` al encolar. Ignorarla rompería un
    camino que ya tenía su gobierno.

    `FORBIDDEN` no se abre con una bandera. Nunca.
    """
    base = authorize(operation)
    if base.allowed or base.autonomy_class is AutonomyClass.FORBIDDEN:
        return base
    datos = payload if isinstance(payload, dict) else {}
    if bool(datos.get("human_approved")):
        return AutonomyDecision(
            operation=base.operation,
            autonomy_class=base.autonomy_class,
            allowed=True,
            requires_human=False,
            reason="Autorizada por una persona: el payload trae `human_approved`.",
        )
    sello = str(datos.get("autonomy_precleared") or "").strip()
    if sello in PRECLEARING_AUTHORITIES:
        return AutonomyDecision(
            operation=base.operation,
            autonomy_class=base.autonomy_class,
            allowed=True,
            requires_human=False,
            reason=(
                f"Gobierno previo de `{sello}`: la decisión ya se tomó antes de "
                "encolar y no se re-decide aquí."
            ),
        )
    return base


def authorize_task(
    task_type: str | None, payload: dict[str, Any] | None = None
) -> AutonomyDecision:
    """Autoriza un tipo de tarea de los Living Workers.

    Un tipo sin operación declarada cae en `HUMAN_REQUIRED` por el mismo camino
    que cualquier operación desconocida: se falla cerrado.
    """
    nombre = str(task_type or "").strip()
    operacion = TASK_OPERATION.get(nombre)
    if operacion is None:
        decision = authorize(nombre or None)
        return AutonomyDecision(
            operation=nombre or "<vacío>",
            autonomy_class=decision.autonomy_class,
            allowed=False,
            requires_human=True,
            reason=(
                f"El tipo de tarea {nombre!r} no tiene operación declarada en "
                "el registro de autonomía: se exige humano por defecto."
            ),
        )
    return authorize_operation(operacion, payload)

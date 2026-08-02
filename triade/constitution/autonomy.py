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

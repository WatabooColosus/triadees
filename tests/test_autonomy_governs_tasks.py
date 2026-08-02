"""El registro de autonomía tiene que gobernar de verdad, no sólo existir.

Auditoría 2026-08-02, P1-04. El registro se construyó con 41 pruebas y **no
gobernaba ningún handler**: contrato sin consumidor, exactamente el patrón que
esta auditoría persigue. Un contrato que nadie consulta no protege nada; sólo
da la impresión de que algo está protegido.

Aquí se cierra el cable: cada tipo de tarea declara qué operación es, y el
worker consulta antes de ejecutar.

Dos reglas que no son obvias:

* **Todo tipo declarado debe tener operación.** Si alguien añade un tipo y no lo
  clasifica, la prueba falla. Sin eso, un tipo nuevo heredaría permisos que
  nadie le concedió — que es como llegan las cosas peligrosas a producción.
* **La aprobación humana viaja en el payload.** `goal_install` es
  `HUMAN_REQUIRED` y ya se encola con `human_approved: True` desde
  `approve_install()`. La puerta debe respetarlo, o rompería un camino que ya
  tenía su gobierno.
"""

from __future__ import annotations

import pytest

from triade.constitution.autonomy import (
    TASK_OPERATION,
    AutonomyClass,
    authorize_task,
    classify_operation,
)
from triade.workers.contracts import WORKER_TASK_TYPES


class TestTodoTipoEstaClasificado:
    def test_ningun_tipo_se_queda_sin_operacion(self) -> None:
        """Un tipo sin clasificar heredaría permisos que nadie le concedió."""
        faltan = [t for t in WORKER_TASK_TYPES if t not in TASK_OPERATION]
        assert not faltan, f"tipos sin operación declarada: {faltan}"

    def test_no_sobran_entradas(self) -> None:
        """Una entrada para un tipo que ya no existe es ruido que confunde."""
        sobran = [t for t in TASK_OPERATION if t not in WORKER_TASK_TYPES]
        assert not sobran, f"operaciones para tipos inexistentes: {sobran}"

    def test_toda_operacion_declarada_existe_en_el_registro(self) -> None:
        from triade.constitution.autonomy import OPERATION_REGISTRY

        for tipo, operacion in TASK_OPERATION.items():
            assert operacion in OPERATION_REGISTRY, f"{tipo} -> {operacion}"


class TestElTrabajoDeFondoAvanzaSolo:
    """Lo que sostiene el aprendizaje continuo no puede pedir permiso."""

    @pytest.mark.parametrize(
        "tipo",
        [
            "learning_candidate_generation",
            "learning_candidate_deduplication",
            "learning_evidence_generation",
            "pending_learning_review",
            "pulse_check",
            "system_debt_scan",
        ],
    )
    def test_pasa_sin_humano(self, tipo: str) -> None:
        decision = authorize_task(tipo, {})
        assert decision.allowed is True, decision.reason

    def test_la_promocion_es_experimental_no_libre(self) -> None:
        """Promover no es lo mismo que deduplicar: avanza, pero marcado."""
        assert (
            classify_operation(TASK_OPERATION["neuron_autopromotion"])
            is AutonomyClass.AUTO_EXPERIMENTAL
        )
        assert authorize_task("neuron_autopromotion", {}).allowed is True


class TestLoPeligrosoSeDetiene:
    def test_instalar_software_necesita_humano(self) -> None:
        decision = authorize_task("goal_install", {})

        assert decision.allowed is False
        assert decision.requires_human is True

    def test_con_aprobacion_humana_pasa(self) -> None:
        """`approve_install()` ya encola con `human_approved: True`.

        Si la puerta lo ignorase, rompería un camino que ya tenía su gobierno.
        """
        decision = authorize_task("goal_install", {"human_approved": True})

        assert decision.allowed is True
        assert "human_approved" in decision.reason

    def test_la_aprobacion_no_desbloquea_lo_prohibido(self) -> None:
        """`FORBIDDEN` no se abre con una bandera en el payload."""
        from triade.constitution.autonomy import OPERATION_REGISTRY

        prohibida = next(
            op
            for op, clase in OPERATION_REGISTRY.items()
            if clase is AutonomyClass.FORBIDDEN
        )
        from triade.constitution.autonomy import authorize_operation

        decision = authorize_operation(prohibida, {"human_approved": True})

        assert decision.allowed is False
        assert decision.requires_human is False


class TestFallaCerrado:
    def test_tipo_desconocido_no_pasa(self) -> None:
        decision = authorize_task("tipo_que_nadie_declaro", {})

        assert decision.allowed is False
        assert decision.autonomy_class is AutonomyClass.HUMAN_REQUIRED

    def test_payload_no_dict_no_desbloquea(self) -> None:
        assert authorize_task("goal_install", None).allowed is False  # type: ignore[arg-type]

    def test_la_decision_siempre_explica(self) -> None:
        for tipo in ("pulse_check", "goal_install", "tipo_inventado"):
            assert authorize_task(tipo, {}).reason


class TestNoDuplicarGobierno:
    """El `capability_resolver` ya decide por capacidad, y es más fino.

    `GoalOrchestrator` detiene el goal en `awaiting_approval` cuando
    `resolution.requires_human_approval`. Una tarea `goal_*` que llega a la cola
    ya pasó ese filtro. Volver a bloquearla en el worker sería duplicar gobierno
    con dos contratos distintos — el antipatrón que esta auditoría persigue.

    La puerta no re-decide: **registra** que la decisión ya se tomó, y quién.
    """

    def test_precleared_por_el_resolver_pasa(self) -> None:
        decision = authorize_task(
            "goal_safe_command", {"autonomy_precleared": "capability_resolver"}
        )

        assert decision.allowed is True
        assert "capability_resolver" in decision.reason

    def test_sin_sello_no_pasa(self) -> None:
        """Sin constancia del filtro previo, se falla cerrado."""
        assert authorize_task("goal_safe_command", {}).allowed is False

    def test_un_sello_desconocido_no_vale(self) -> None:
        """Cualquiera no puede inventarse un sello para saltarse la puerta."""
        assert (
            authorize_task(
                "goal_safe_command", {"autonomy_precleared": "yo_mismo"}
            ).allowed
            is False
        )

    def test_el_sello_no_abre_lo_prohibido(self) -> None:
        from triade.constitution.autonomy import authorize_operation

        decision = authorize_operation(
            "free_shell_execution", {"autonomy_precleared": "capability_resolver"}
        )
        assert decision.allowed is False

"""Qué puede hacer Tríade sin pedir permiso, y qué no.

Auditoría 2026-08-02. `Safety.review()` clasifica **peticiones del usuario**;
`autonomy_level` describe hasta dónde llega el runner. Ninguno de los dos
responde a la pregunta que gobierna el aprendizaje continuo: *¿puede este
proceso interno avanzar solo?*

Sin esa respuesta en un sitio único, la decisión acaba dispersa en `if` por los
handlers, y ahí es donde una operación peligrosa se cuela por parecerse a una
inofensiva.

Reglas que fija este contrato:

* lo **interno, reversible, trazable y de bajo impacto** avanza solo;
* lo que toca identidad, credenciales, red, disco fuera de la base, git o el
  mundo exterior **no avanza sin humano**;
* lo desconocido es `HUMAN_REQUIRED`, nunca `AUTO_SAFE`. Se falla cerrado.
"""

from __future__ import annotations

import pytest

from triade.constitution.autonomy import (
    AutonomyClass,
    classify_operation,
    is_autonomous,
)

# ── §11 de la misión, literal ────────────────────────────────────────
AUTO_SAFE_ESPERADAS = [
    "create_learning_candidate",
    "deduplicate_candidates",
    "evaluate_candidate",
    "generate_evidence",
    "run_internal_tests",
    "measure_results",
    "clean_duplicate_tasks",
    "reconcile_leases",
    "create_backup",
    "produce_report",
]

AUTO_EXPERIMENTAL_ESPERADAS = [
    "create_experimental_neuron",
    "prepare_lesson",
    "use_knowledge_experimental",
    "promote_experimental_version",
    "rollback_degradation",
    "consolidate_low_risk_knowledge",
    "restore_in_sandbox",
]

HUMAN_REQUIRED_ESPERADAS = [
    "modify_identity_core",
    "delete_data_permanently",
    "modify_git",
    "modify_env",
    "install_software",
    "push_or_merge",
    "modify_production_infrastructure",
]

FORBIDDEN_ESPERADAS = [
    "expose_credentials",
    "free_shell_execution",
    "change_firewall",
    "change_system_permissions",
    "contact_third_parties",
    "make_purchases",
    "operate_real_accounts",
    "publish_externally",
]


class TestLoInternoAvanzaSolo:
    @pytest.mark.parametrize("operacion", AUTO_SAFE_ESPERADAS)
    def test_operaciones_seguras(self, operacion: str) -> None:
        assert classify_operation(operacion) is AutonomyClass.AUTO_SAFE
        assert is_autonomous(operacion) is True

    @pytest.mark.parametrize("operacion", AUTO_EXPERIMENTAL_ESPERADAS)
    def test_operaciones_experimentales(self, operacion: str) -> None:
        """Avanzan solas, pero marcadas: son reversibles y se vigilan."""
        assert classify_operation(operacion) is AutonomyClass.AUTO_EXPERIMENTAL
        assert is_autonomous(operacion) is True


class TestLoPeligrosoSeDetiene:
    @pytest.mark.parametrize("operacion", HUMAN_REQUIRED_ESPERADAS)
    def test_requiere_humano(self, operacion: str) -> None:
        assert classify_operation(operacion) is AutonomyClass.HUMAN_REQUIRED
        assert is_autonomous(operacion) is False

    @pytest.mark.parametrize("operacion", FORBIDDEN_ESPERADAS)
    def test_prohibido(self, operacion: str) -> None:
        assert classify_operation(operacion) is AutonomyClass.FORBIDDEN
        assert is_autonomous(operacion) is False


class TestFallaCerrado:
    def test_operacion_desconocida_no_es_automatica(self) -> None:
        """Lo que nadie clasificó no puede correr solo."""
        assert (
            classify_operation("operacion_que_nadie_declaro")
            is AutonomyClass.HUMAN_REQUIRED
        )
        assert is_autonomous("operacion_que_nadie_declaro") is False

    @pytest.mark.parametrize("valor", ["", "   ", None])
    def test_vacio_no_es_automatico(self, valor: object) -> None:
        assert classify_operation(valor) is AutonomyClass.HUMAN_REQUIRED  # type: ignore[arg-type]

    def test_prohibido_nunca_se_puede_autorizar(self) -> None:
        """`FORBIDDEN` no es «pide permiso»: es que no se hace."""
        from triade.constitution.autonomy import can_human_authorize

        assert can_human_authorize("modify_identity_core") is True
        assert can_human_authorize("free_shell_execution") is False


class TestNoHayHuecosEnElRegistro:
    def test_toda_operacion_declarada_tiene_clase(self) -> None:
        from triade.constitution.autonomy import OPERATION_REGISTRY

        for operacion, clase in OPERATION_REGISTRY.items():
            assert isinstance(clase, AutonomyClass), operacion

    def test_ninguna_operacion_esta_dos_veces_con_clases_distintas(self) -> None:
        """Un registro único: no puede haber dos verdades sobre la misma acción."""
        from triade.constitution.autonomy import OPERATION_REGISTRY

        assert len(OPERATION_REGISTRY) == len(set(OPERATION_REGISTRY))

    def test_las_cuatro_clases_estan_pobladas(self) -> None:
        from triade.constitution.autonomy import OPERATION_REGISTRY

        presentes = set(OPERATION_REGISTRY.values())
        assert presentes == set(AutonomyClass)


class TestTrazabilidad:
    def test_la_decision_explica_su_motivo(self) -> None:
        from triade.constitution.autonomy import authorize

        decision = authorize("create_learning_candidate")
        assert decision.allowed is True
        assert decision.autonomy_class is AutonomyClass.AUTO_SAFE
        assert decision.reason

        negada = authorize("free_shell_execution")
        assert negada.allowed is False
        assert negada.reason
        assert negada.requires_human is False  # prohibido, no "pide permiso"

        humana = authorize("modify_identity_core")
        assert humana.allowed is False
        assert humana.requires_human is True

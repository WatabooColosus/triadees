"""El circuito de automejora no podía empezar, y el umbral no existía.

Dos fallos encadenados, medidos el 2026-08-10 con todas estas tablas a cero:
`improvement_proposals`, `improvement_candidate_links`, `improvement_canaries`,
`improvement_canary_observations`, `neuron_candidates`.

1. **La cadena no podía empezar.** `MissionPlanner._plan_self_improvement` sólo
   encolaba `self_improvement_evaluation` cuando ya había propuestas
   `approved`. Pero lo único que aprueba sin humano vive *dentro* de ese
   handler, así que una propuesta `open` no podía llegar a `approved` por sí
   sola. El código de auto-aprobación era inalcanzable salvo que una persona
   aprobara antes a mano — justo lo que la política venía a evitar.

2. **No había listón.** Cuando la tarea llegaba a ejecutarse, aprobaba la
   primera propuesta abierta que encontrara sin mirar la calidad de la señal.

El responsable autorizó el 2026-08-11 la aprobación autónoma **sólo por encima
de 0.94**. Lo que se comprueba aquí es que ese listón se aplica, que no se puede
rodear por la puerta de atrás, y que un rechazo gobernado deja rastro en vez de
silencio: una propuesta que no pasa el umbral no es un fallo del circuito, es el
circuito funcionando.
"""

from __future__ import annotations

import pytest

from triade.self_improvement import auto_approval


@pytest.fixture(autouse=True)
def _politica_encendida(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE", "1")
    monkeypatch.delenv(
        "TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE_MIN_CONFIDENCE", raising=False
    )


_ABIERTA = {"requires_human_approval": False}


def test_confianza_alta_se_aprueba_sola() -> None:
    decision = auto_approval.evaluate(_ABIERTA, {"confidence": 0.96})
    assert decision.allowed is True
    assert decision.confidence == 0.96
    assert decision.threshold == 0.94


def test_justo_en_el_umbral_pasa() -> None:
    assert auto_approval.evaluate(_ABIERTA, {"confidence": 0.94}).allowed is True


def test_confianza_baja_se_rechaza_y_lo_dice() -> None:
    """El caso real: la señal viva de la base tiene confianza 0.4."""
    decision = auto_approval.evaluate(_ABIERTA, {"confidence": 0.4})
    assert decision.allowed is False
    assert "0.40" in decision.reason
    assert "0.94" in decision.reason


def test_impacto_alto_no_compensa_confianza_baja() -> None:
    """Se mira la confianza, no el impacto, y esta es la razón de que así sea."""
    decision = auto_approval.evaluate(
        _ABIERTA, {"confidence": 0.3, "impact": 1.0, "priority": 1.0}
    )
    assert decision.allowed is False


def test_requires_human_approval_no_bloquea_aqui() -> None:
    """El candado de `requires_human_approval` NO va en este paso, y es a propósito.

    Es tentador usarlo como tercer candado. Sería un error: ese campo lo exige
    el store al *crear* una propuesta de riesgo alto, y el gate duro se movió a
    `stable_promotion_gate` —experimental → estable, el paso irreversible—
    porque exigir firma para *proponer* dejaba el circuito inerte esperando a
    alguien. Bloquear aquí devolvería el subsistema a cero justo para el caso
    que existe en producción: la única señal viva es de riesgo alto.
    """
    decision = auto_approval.evaluate(
        {"requires_human_approval": True}, {"confidence": 0.96}
    )
    assert decision.allowed is True

    # Y con confianza baja se rechaza igual, venga como venga la propuesta.
    assert (
        auto_approval.evaluate(
            {"requires_human_approval": True}, {"confidence": 0.4}
        ).allowed
        is False
    )


def test_sin_confianza_declarada_no_se_aprueba() -> None:
    assert auto_approval.evaluate(_ABIERTA, {}).allowed is False
    assert auto_approval.evaluate(_ABIERTA, {"confidence": None}).allowed is False
    assert auto_approval.evaluate(_ABIERTA, {"confidence": "alta"}).allowed is False


def test_politica_apagada_manda_sobre_todo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE", "0")
    assert auto_approval.evaluate(_ABIERTA, {"confidence": 1.0}).allowed is False


def test_la_autorizacion_permanente_no_borra_el_prefijo_automatico(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El responsable autorizo que estas aprobaciones lleven su nombre.

    Su nombre se estampa detras del prefijo `auto:`, no en su lugar. Una firma
    humana indistinguible de una automatica no protege a quien firma: le
    atribuye decisiones que no miro. El nombre vive en el entorno, fuera de git,
    porque acaba escrito en la base y en los informes.
    """
    monkeypatch.setenv("TRIADE_SELF_IMPROVEMENT_POLICY_AUTHORIZER", "Responsable")
    aprobador = auto_approval.policy_approver()
    assert aprobador.startswith("auto:")
    assert "Responsable" in aprobador

    monkeypatch.delenv("TRIADE_SELF_IMPROVEMENT_POLICY_AUTHORIZER", raising=False)
    assert auto_approval.policy_approver() == "auto:threshold_policy"


def test_umbral_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE_MIN_CONFIDENCE", "0.5")
    assert auto_approval.evaluate(_ABIERTA, {"confidence": 0.6}).allowed is True


@pytest.mark.parametrize("valor", ["", "no-es-un-numero", "1.5", "-0.2"])
def test_umbral_ilegible_no_baja_el_liston(
    monkeypatch: pytest.MonkeyPatch, valor: str
) -> None:
    """Un valor roto en el entorno no puede convertirse en «apruébalo todo»."""
    monkeypatch.setenv("TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE_MIN_CONFIDENCE", valor)
    assert auto_approval.min_confidence() == 0.94
    assert auto_approval.evaluate(_ABIERTA, {"confidence": 0.5}).allowed is False


def test_el_aprobador_nunca_se_firma_como_humano() -> None:
    assert auto_approval.POLICY_APPROVER.startswith("auto:")

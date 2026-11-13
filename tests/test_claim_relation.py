"""§8 — relación entre dos afirmaciones, sin acusar por defecto.

El par del 2026-08-26 que el sistema dio por contradictorio:

    A: «la memoria persiste entre sesiones»
    B: «el recall es selectivo y no garantiza recuperar cada detalle»

No lo son, y `memory_truth_snapshot()` publica las dos como ciertas a la vez.
"""

from __future__ import annotations

import pytest

from triade.os.claim_relation import ClaimRelation, classify_relation

PERSISTE = "la memoria persiste entre sesiones"
RECALL_SELECTIVO = "el recall es selectivo y no garantiza recuperar cada detalle"


def test_persistencia_y_recall_selectivo_son_compatibles():
    """§18.9 — el caso real. Comparten vocabulario y no compiten."""
    veredicto = classify_relation(PERSISTE, RECALL_SELECTIVO)
    assert veredicto.relation is ClaimRelation.COMPATIBLE
    assert "ejes distintos" in veredicto.reason


def test_el_solape_lexico_no_decide():
    """Las dos hablan de memoria; eso las haría parecer más contradictorias.

    Es justo el motivo por el que el criterio no puede ser solape de palabras.
    """
    veredicto = classify_relation(PERSISTE, RECALL_SELECTIVO)
    assert "persistence" in veredicto.left_axes
    assert "retrieval_completeness" in veredicto.right_axes
    assert veredicto.shared_axes == ()


@pytest.mark.parametrize(
    ("izquierda", "derecha"),
    [
        (PERSISTE, "la memoria no persiste entre sesiones"),
        ("la memoria se conserva al cerrar", "todo se borra al cerrar la sesión"),
        ("el recall recupera todo literalmente", "el recall es selectivo"),
    ],
)
def test_una_contradiccion_real_si_se_detecta(izquierda, derecha):
    """Reparar el falso positivo no puede apagar el detector.

    El segundo par no lleva ningún «no»: la polaridad está en el verbo. Sin
    mirar eso, «se conserva» y «se borra» salían compatibles.
    """
    assert classify_relation(izquierda, derecha).relation is ClaimRelation.CONTRADICTION


def test_un_matiz_restringe_pero_no_niega():
    veredicto = classify_relation(PERSISTE, "la memoria persiste pero no siempre")
    assert veredicto.relation is ClaimRelation.ENTAILMENT


def test_sin_eje_reconocible_el_veredicto_es_unknown():
    """`UNKNOWN` antes que acusar: devolver contradicción ante la duda fue el bug."""
    assert classify_relation("hola qué tal", "el cielo es azul").relation is (
        ClaimRelation.UNKNOWN
    )
    assert classify_relation("", "algo").relation is ClaimRelation.UNKNOWN


def test_el_veredicto_explica_por_que():
    """Sin motivo, un veredicto no se puede discutir ni auditar."""
    for izq, der in ((PERSISTE, RECALL_SELECTIVO), (PERSISTE, "no persiste")):
        veredicto = classify_relation(izq, der)
        assert veredicto.reason
        assert veredicto.to_dict()["relation"] == veredicto.relation.value

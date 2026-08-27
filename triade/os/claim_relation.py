"""Qué relación hay entre dos afirmaciones, sin fingir que se sabe más.

Probado sobre un par real durante la batería del 2026-08-26:

    A: «la memoria persiste entre sesiones»
    B: «el recall es selectivo y no garantiza recuperar cada detalle»

El sistema las dio por contradictorias. No lo son, y además **el propio modelo
de verdad de Tríade afirma las dos a la vez**: `memory_truth_snapshot()` publica
`session_boundary_does_not_delete_memory` y `recall_is_selective_not_total`
como ciertas simultáneamente.

## Por qué no había nada que arreglar en el grafo

`kg_edges` y `kg_contradictions` estaban a cero, y su detector
(`project_research_into_graph`) compara **claves de investigación**: misma
`claim_key`, valores distintos, fuentes distintas. Sirve para «altura = 8848 m»
contra «altura = 8849 m». Una pregunta conversacional sobre dos frases nunca
llega ahí. El veredicto lo producía el modelo por su cuenta, sin ninguna ruta
que lo comprobara.

## El criterio

Dos afirmaciones se contradicen cuando dicen cosas **incompatibles del mismo
sujeto en el mismo eje**. Un eje es lo que se predica: que algo persista y que
su recuperación sea selectiva son ejes distintos, así que pueden ser ciertas a
la vez por mucho vocabulario que compartan.

Esto es deliberadamente lo contrario de medir solape léxico. Las dos frases del
caso comparten «memoria» y hablan del mismo objeto; el solape las habría hecho
parecer más contradictorias, no menos.

`UNKNOWN` es una respuesta de primera clase y la más honesta cuando no se puede
establecer sujeto o eje. Devolver `CONTRADICTION` por defecto es lo que produjo
el fallo: ante la duda, el sistema acusaba.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum

__all__ = ["ClaimRelation", "RelationVerdict", "classify_relation"]


class ClaimRelation(str, Enum):
    """Relación entre dos afirmaciones."""

    ENTAILMENT = "entailment"
    COMPATIBLE = "compatible"
    CONTRADICTION = "contradiction"
    UNKNOWN = "unknown"


#: Ejes de predicación. Cada eje agrupa las formas de decir lo mismo.
#:
#: No son «temas»: son **lo que se afirma**. Dos frases sobre la memoria pueden
#: caer en ejes distintos —uno sobre si sobrevive, otro sobre si se recupera
#: entera— y entonces no compiten.
#: Cada eje se declara en dos mitades: las marcas que **afirman** el eje y las
#: que lo **niegan** léxicamente. Sin esta separación, «se conserva al cerrar» y
#: «se borra al cerrar» caían en el mismo eje con la misma polaridad —ninguna
#: lleva un «no»— y salían compatibles. La polaridad de una frase no está sólo
#: en la negación gramatical: está en el verbo que elige.
_EJES: dict[str, dict[str, tuple[str, ...]]] = {
    "persistence": {
        "afirma": (
            "persist",
            "sobreviv",
            "se conserva",
            "se guarda",
            "se mantiene",
            "entre sesiones",
            "fuera de la sesion",
            "fuera de cada sesion",
        ),
        "niega": ("se borra", "se pierde", "desaparec", "se elimina", "se olvida"),
    },
    "retrieval_completeness": {
        "afirma": ("recupera todo", "recuerda todo", "literalmente todo", "exhaustiv"),
        "niega": ("selectiv", "parcial", "no cada detalle", "no todo"),
    },
    "identity": {
        "afirma": ("se llama", "identidad", "nombre", "soy ", "es triade"),
        "niega": (),
    },
    "quantity": {"afirma": ("cuant", "numero", "total de", "cantidad"), "niega": ()},
}

#: Marcas que sitúan la frase en el eje de recuperación sin fijar polaridad por
#: sí solas: «recall», «recupera», «cada detalle». Necesarias para reconocer de
#: qué se habla, inútiles para decidir si se afirma o se niega.
_EJES_NEUTROS: dict[str, tuple[str, ...]] = {
    "retrieval_completeness": ("recall", "recupera", "cada detalle", "recuerd"),
    "persistence": ("al cerrar", "al reiniciar"),
}

#: Marcas de negación. La polaridad es lo que decide dentro de un mismo eje.
_NEGACIONES = (
    "no ",
    "nunca",
    "jamas",
    "ninguna",
    "ningun",
    "sin ",
    "tampoco",
    "deja de",
)

#: Marcas de que una afirmación restringe a la otra en lugar de negarla.
#: «no garantiza», «no siempre», «no todo» matizan; no niegan el eje entero.
_MATICES = (
    "no garantiza",
    "no siempre",
    "no todo",
    "no necesariamente",
    "no cada",
    "no implica",
)


@dataclass(frozen=True, slots=True)
class RelationVerdict:
    """El veredicto y **por qué**, que es lo que permite discutirlo."""

    relation: ClaimRelation
    reason: str
    shared_axes: tuple[str, ...] = ()
    left_axes: tuple[str, ...] = ()
    right_axes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "relation": self.relation.value,
            "reason": self.reason,
            "shared_axes": list(self.shared_axes),
            "left_axes": list(self.left_axes),
            "right_axes": list(self.right_axes),
        }


def _normalize(text: str) -> str:
    plano = unicodedata.normalize("NFKD", str(text or ""))
    plano = "".join(ch for ch in plano if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]+", " ", plano.lower())).strip()


def _axes(plain: str) -> frozenset[str]:
    encontrados = set()
    for eje, mitades in _EJES.items():
        if any(m in plain for m in (*mitades["afirma"], *mitades["niega"])):
            encontrados.add(eje)
    for eje, neutras in _EJES_NEUTROS.items():
        if any(m in plain for m in neutras):
            encontrados.add(eje)
    return frozenset(encontrados)


def _polarity(plain: str, eje: str) -> bool | None:
    """¿La frase afirma el eje (`True`), lo niega (`False`) o no se sabe?

    Se combinan dos fuentes: el verbo elegido —«se conserva» frente a «se
    borra»— y la negación gramatical, que invierte lo anterior. Un matiz no
    invierte nada: ver `_has_negation`.
    """
    mitades = _EJES.get(eje)
    if mitades is None:
        return None
    afirma = any(m in plain for m in mitades["afirma"])
    niega = any(m in plain for m in mitades["niega"])
    if afirma == niega:  # ninguna marca, o las dos: sin señal léxica
        base: bool | None = None
    else:
        base = afirma
    if base is None:
        return None
    return not base if _has_negation(plain) else base


def _has_negation(plain: str) -> bool:
    # Un matiz no es una negación: «no garantiza recuperar cada detalle» acota
    # el alcance, no afirma lo contrario. Se comprueba antes justamente porque
    # todos los matices empiezan por «no».
    sin_matices = plain
    for matiz in _MATICES:
        sin_matices = sin_matices.replace(matiz, " ")
    return any(neg in f" {sin_matices} " for neg in _NEGACIONES)


def _is_qualifier(plain: str) -> bool:
    return any(matiz in plain for matiz in _MATICES)


def classify_relation(left: str, right: str) -> RelationVerdict:
    """Clasifica el par sin inventarse certeza.

    El orden importa para `ENTAILMENT`: se lee «`left` implica `right`».
    """
    izq, der = _normalize(left), _normalize(right)
    if not izq or not der:
        return RelationVerdict(
            ClaimRelation.UNKNOWN, "una de las afirmaciones está vacía"
        )

    ejes_izq, ejes_der = _axes(izq), _axes(der)
    comunes = ejes_izq & ejes_der

    if not ejes_izq or not ejes_der:
        return RelationVerdict(
            ClaimRelation.UNKNOWN,
            "no se pudo establecer qué se predica en al menos una",
            left_axes=tuple(sorted(ejes_izq)),
            right_axes=tuple(sorted(ejes_der)),
        )

    if not comunes:
        # El caso del 2026-08-26: `persistence` frente a
        # `retrieval_completeness`. Comparten vocabulario y no compiten.
        return RelationVerdict(
            ClaimRelation.COMPATIBLE,
            "hablan de ejes distintos: pueden ser ciertas a la vez",
            left_axes=tuple(sorted(ejes_izq)),
            right_axes=tuple(sorted(ejes_der)),
        )

    # La polaridad se decide **por eje**, no sobre la frase entera: una misma
    # frase puede afirmar un eje y matizar otro.
    for eje in sorted(comunes):
        pol_izq, pol_der = _polarity(izq, eje), _polarity(der, eje)
        if pol_izq is None or pol_der is None:
            continue
        if pol_izq != pol_der:
            return RelationVerdict(
                ClaimRelation.CONTRADICTION,
                f"eje «{eje}» afirmado y negado a la vez",
                shared_axes=tuple(sorted(comunes)),
                left_axes=tuple(sorted(ejes_izq)),
                right_axes=tuple(sorted(ejes_der)),
            )

    # Mismo eje, misma polaridad. Si una matiza a la otra, la restringe: la
    # general implica el marco de la matizada, no la contradice.
    if _is_qualifier(der) and not _is_qualifier(izq):
        return RelationVerdict(
            ClaimRelation.ENTAILMENT,
            "la segunda restringe el alcance de la primera, no la niega",
            shared_axes=tuple(sorted(comunes)),
            left_axes=tuple(sorted(ejes_izq)),
            right_axes=tuple(sorted(ejes_der)),
        )

    return RelationVerdict(
        ClaimRelation.COMPATIBLE,
        "mismo eje y misma polaridad",
        shared_axes=tuple(sorted(comunes)),
        left_axes=tuple(sorted(ejes_izq)),
        right_axes=tuple(sorted(ejes_der)),
    )

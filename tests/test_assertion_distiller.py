"""La verja de sujeto: qué entra en la cola como aserción y qué no.

Los casos no son inventados. Son las 14 afirmaciones que `distill_rules` sacó
de los candidatos `web` reales el 2026-08-26, con la etiqueta que les puso una
persona. Si alguien relaja los umbrales, estos tests dicen qué se rompe.
"""

from __future__ import annotations

from triade.learning.assertion_distiller import (
    a_snake,
    capitalizada_no_inicial,
    distill_assertion,
    es_sujeto,
)
from triade.learning.knowledge_probe import extract_target

# «El Cuarteto de Nos es una banda de rock uruguaya…» — nombre propio, y además
# se repite a lo largo del artículo.
FUENTE_BUENA = (
    "El Cuarteto de Nos es una banda de rock uruguaya formada en Montevideo. "
    "El Cuarteto de Nos ha publicado numerosos discos. "
    "La crítica considera al Cuarteto de Nos una de las bandas más influyentes."
)

# «…supone un cambio muy notable es un cambio de actitud…» — el patrón `es un`
# arrastró un fragmento adverbial que no nombra nada.
FUENTE_FRAGMENTO = (
    "Lo que ocurre después supone un cambio muy notable es un cambio de "
    "actitud o de ideas ante la realidad."
)

# «The following modules are available: …» — forma de definición, sujeto vacío.
FUENTE_NAVEGACION = (
    "The following modules are available: Core functionality ( core ) - a "
    "compact module defining basic data structures, including matrices."
)


def test_un_nombre_propio_es_sujeto() -> None:
    assert es_sujeto("cuarteto de nos", FUENTE_BUENA)
    assert capitalizada_no_inicial("cuarteto de nos", FUENTE_BUENA) >= 1


def test_un_fragmento_adverbial_no_es_sujeto() -> None:
    """`muy notable` no nombra nada: ni va capitalizado ni reaparece."""
    assert not es_sujeto("muy notable", FUENTE_FRAGMENTO)


def test_una_frase_de_navegacion_no_es_sujeto() -> None:
    """`following modules` tiene forma de definición y no define nada."""
    assert not es_sujeto("following modules", FUENTE_NAVEGACION)


def test_una_descripcion_definida_no_es_sujeto() -> None:
    """`premio final de la competencia` depende de un contexto que no lleva.

    Como cloze sería irresoluble para el control y trivial para el tratamiento
    —que lee la respuesta de la memoria inyectada—, es decir un `improved`
    fabricado.
    """
    fuente = (
        "El premio final de la competencia es una suma de alrededor de 500 "
        "millones de pesos, adicional a las recompensas ya entregadas."
    )
    assert not es_sujeto("premio final de la competencia", fuente)


def test_la_recurrencia_rescata_un_sujeto_en_minusculas() -> None:
    """Un concepto genérico real reaparece; un fragmento no.

    Es la segunda señal, independiente de la capitalización: sin ella se
    perderían términos técnicos que la fuente nunca escribe con mayúscula.
    """
    fuente = (
        "Una cantiga es un tipo de composición poética destinada a ser "
        "cantada. La cantiga medieval gallega tuvo gran difusión, y cada "
        "cantiga se acompañaba de música."
    )
    assert capitalizada_no_inicial("cantiga", fuente) == 0, "no va capitalizada"
    assert es_sujeto("cantiga", fuente), "pero reaparece tres veces"


def test_la_clave_pasa_a_snake_conservando_tildes() -> None:
    """Quitar la tilde cambiaría el dato afirmado, no sólo su forma."""
    assert a_snake("Día del Amigo") == "día_del_amigo"
    assert a_snake("«Hoy tengo ganas de ti»") == "hoy_tengo_ganas_de_ti"


def test_la_ascercion_destilada_es_sondeable() -> None:
    """El punto entero: lo que sale de aquí tiene que darle target a la sonda."""
    asercion = distill_assertion(FUENTE_BUENA)
    assert asercion is not None
    assert asercion["key"] == "cuarteto_de_nos"
    assert extract_target(asercion["content"]) == "cuarteto_de_nos"


def test_una_fuente_sin_sujeto_no_produce_asercion() -> None:
    """`None` es la respuesta correcta, y la más frecuente."""
    assert distill_assertion(FUENTE_FRAGMENTO) is None
    assert distill_assertion(FUENTE_NAVEGACION) is None
    assert distill_assertion("") is None
    assert distill_assertion("   ") is None


def test_una_clave_de_una_sola_palabra_no_sirve_de_sonda() -> None:
    """`_DISTINTIVO` exige un guión bajo: sin él no hay token distintivo.

    Forzarlo aquí —inventando un `_` que la clave no tiene— sería mentirle a la
    sonda para que acepte un candidato que no es medible.
    """
    fuente = (
        "Javadoc es una utilidad de Oracle para la generación de "
        "documentación de APIs. Javadoc lee el código fuente. Con Javadoc se "
        "genera HTML."
    )
    assert es_sujeto("javadoc", fuente), "el sujeto es válido…"
    assert distill_assertion(fuente) is None, "…pero una palabra no es sondeable"


def test_una_transcripcion_de_run_no_produce_asercion() -> None:
    """Las 60 conversacionales elegibles son salidas del propio modelo.

    Destilarlas mediría que el modelo repite lo que dijo, no que aprendió algo.
    `is_unverified_transcript` ya las rechaza aguas abajo; aquí se comprueba que
    tampoco entran por esta puerta.
    """
    transcripcion = (
        "run_id: run-20260728-234411-c6b24598\n"
        "source: react-ui\n"
        "intent: conversation\n"
        "input: hola como estas\n"
        "response: No siento como una persona, pero estoy operando.\n"
        "verification_status: ok"
    )
    assert distill_assertion(transcripcion) is None

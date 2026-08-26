"""Convierte una fuente en una **aserción sobre el mundo** que sí es sondeable.

`learning_queue` guarda la transcripción cruda de lo que pasó. `extract_target()`
—correctamente— dice `None` ante un texto que no afirma ningún hecho, y sin
target no hay sonda, sin sonda no hay evidencia y sin evidencia nada llega a
`stable`. Medido el 2026-08-26: de 149 candidatos elegibles, **0** eran medibles,
y `learning_evidence_generation` llevaba parada desde el 12 de agosto.

Este módulo cierra ese hueco, pero con un cerrojo que no es opcional.

## Por qué hace falta una verja de sujeto

El brazo de tratamiento de `evidence_producer` **inyecta el candidato** (lo exige
en `treatment_sin_inyeccion`). La sonda es un cloze sobre el propio contenido,
así que el tratamiento responde **leyendo la memoria inyectada**. Eso significa
que *cualquier* clave bien formada produce `improved`, diga algo del mundo o no.

Destilar sin filtrar convertiría 0 `stable` en cientos, todos fabricados. La
medición no protege de esto: es la verja o nada.

## Qué separa un sujeto de un fragmento

Medido sobre las 14 afirmaciones que las reglas sacaron de los candidatos `web`
reales, dos señales independientes no dieron **ningún** falso positivo:

- ``capitalizada_no_inicial``: alguna palabra con contenido de la clave aparece
  Capitalizada en la fuente sin ser principio de frase. Un nombre propio lo está
  («Cuarteto de Nos»); un fragmento arrastrado por el patrón no («muy notable»).
- ``recurrencia``: la clave aparece ≥ 2 veces en la fuente. Un tema real vuelve;
  un fragmento aparece una vez y no reaparece.

Las tres claves malas de la muestra —``muy notable``, ``following modules`` y
``premio final de la competencia``— fallan **las dos**. Ocho de las once buenas
pasan al menos una. Se acepta esa pérdida: un falso negativo cuesta un candidato,
un falso positivo cuesta un `stable` inventado, y eso envenena la memoria.

**La muestra es de 14 casos y la etiqueta la puso una persona.** La precisión
observada es sobre eso, no sobre la población. Al ampliar, revisar antes de
relajar los umbrales.
"""

from __future__ import annotations

import re
import unicodedata

from triade.research.claim_distiller import distill_claims

#: Palabras sin contenido: no aportan señal de nombre propio y aparecen
#: capitalizadas por accidente al empezar frase.
_VACIAS = frozenset(
    {
        "de",
        "del",
        "la",
        "el",
        "los",
        "las",
        "un",
        "una",
        "unos",
        "unas",
        "y",
        "o",
        "a",
        "en",
        "con",
        "por",
        "para",
        "al",
        "of",
        "the",
        "and",
        "or",
        "an",
        "in",
        "on",
        "for",
        "to",
    }
)

#: Mínimo de repeticiones en la fuente para aceptar una clave que no aparece
#: capitalizada. Con 1 entraban los tres fragmentos de la muestra.
_MIN_RECURRENCIA = 2


def _palabras_con_contenido(clave: str) -> list[str]:
    return [p for p in clave.split() if p.strip("«»\"'()") and p not in _VACIAS]


def capitalizada_no_inicial(clave: str, fuente: str) -> int:
    """Palabras de la clave que aparecen Capitalizadas sin abrir frase.

    El `(?<![.!?]\\s)` y el `(?<!^)` son el punto entero de la función: sin
    ellos, cualquier clave que empiece una frase parecería nombre propio y la
    señal no separaría nada.
    """
    aciertos = 0
    for palabra in _palabras_con_contenido(clave):
        limpia = palabra.strip("«»\"'()")
        if not limpia:
            continue
        capitalizada = limpia[0].upper() + limpia[1:]
        patron = r"(?<![.!?]\s)(?<!^)\b" + re.escape(capitalizada) + r"\b"
        if re.search(patron, fuente, re.MULTILINE):
            aciertos += 1
    return aciertos


def recurrencia(clave: str, fuente: str) -> int:
    """Veces que la clave aparece en la fuente, sin distinguir mayúsculas."""
    return len(re.findall(re.escape(clave), fuente, re.IGNORECASE))


def es_sujeto(clave: str, fuente: str) -> bool:
    """¿La clave nombra algo, o es un fragmento que arrastró el patrón?"""
    if not _palabras_con_contenido(clave):
        return False
    return (
        capitalizada_no_inicial(clave, fuente) >= 1
        or recurrencia(clave, fuente) >= _MIN_RECURRENCIA
    )


def a_snake(clave: str) -> str:
    """`Cuarteto de Nos` -> `cuarteto_de_nos`, conservando las tildes.

    Las tildes se conservan a propósito: `extract_target()` ya las admite desde
    el 2026-08-26, y quitarlas aquí cambiaría el dato que se afirma.
    """
    limpia = unicodedata.normalize("NFC", clave.strip().lower())
    limpia = re.sub(r"[^\w\s]", " ", limpia, flags=re.UNICODE)
    return "_".join(limpia.split())


def distill_assertion(
    texto: str, *, question: str = "", extractor: str = "rules"
) -> dict[str, str] | None:
    """Devuelve la mejor aserción sondeable de `texto`, o `None`.

    `None` es una respuesta legítima y la más frecuente: la mayoría de las
    fuentes no afirman ningún hecho con sujeto nombrable, igual que la mayoría
    de los candidatos no son medibles.
    """
    fuente = str(texto or "")
    if not fuente.strip():
        return None

    for claim in distill_claims(fuente, question=question, extractor=extractor):
        clave = str(claim.get("key") or "")
        valor = str(claim.get("value") or "")
        if not clave or not valor or not es_sujeto(clave, fuente):
            continue
        snake = a_snake(clave)
        # Una sola palabra no es un token distintivo para `_DISTINTIVO`: sin
        # guión bajo no casa, y forzarlo aquí sería mentirle a la sonda.
        if "_" not in snake:
            continue
        return {
            "key": snake,
            "value": valor,
            "content": f"{snake}: {valor}",
            "extractor": str(claim.get("extractor") or ""),
        }
    return None

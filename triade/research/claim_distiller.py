"""Convierte texto descargado en afirmaciones comparables entre fuentes.

Era el eslabón que faltaba. `GovernedResearchWorker` sólo crea un candidato de
aprendizaje cuando el material trae `claims`; sin ellas cae en `unverifiable` y
no ingiere nada:

    elif not claims:
        status = "unverifiable"          # governed.py:142

El proveedor web devolvía `url`, `title` y `content`, nunca `claims`. Medido en
producción el 2026-08-09: **153 ejecuciones de `research_curriculum`, todas
`unverifiable`, cero candidatos**. La investigación gobernada no ha podido
escribir material nunca; no es una regresión, es que la pieza no existía.

Por qué una afirmación y no el texto
------------------------------------
El valor de tener dos fuentes independientes es poder contrastarlas, y dos
transcripciones crudas no se contrastan: hace falta un par ``key``/``value``
para que `governed.py` detecte que dos fuentes dicen cosas distintas de lo
mismo y marque `conflicting_sources`. La afirmación es lo que hace verificable
a la evidencia.

Dos extractores, misma salida
-----------------------------
``rules``
    Determinista, sin modelo, auditable: frases definitorias («X es Y»). Es el
    predeterminado justamente porque no depende de nada que pueda alucinar.

``model``
    Un modelo local propone pares. Más cobertura y menos frágil ante la
    redacción, pero **no se le cree**: toda afirmación que proponga se comprueba
    contra el texto de origen y se descarta la que no esté anclada. Un modelo
    dentro de una cadena de evidencia sólo es admisible si su salida se verifica
    contra la fuente, y eso es lo que hace `_anclada()`.

Cada afirmación lleva `extractor`, así que en la evidencia siempre se puede
saber quién la produjo y descartarla por origen si hiciera falta.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

RULE_EXTRACTOR = "rules-1.0.0"
MODEL_EXTRACTOR = "model-1.0.0"

#: Tope por fuente. Una página larga daría decenas de afirmaciones ruidosas y
#: cada una es una oportunidad de choque espurio entre fuentes.
MAX_CLAIMS = 6

#: Un sujeto es una etiqueta corta; si ocupa media frase no es una clave que
#: otra fuente vaya a repetir, y entonces no sirve para contrastar.
MAX_KEY_WORDS = 5
MIN_VALUE_CHARS = 25
MAX_VALUE_CHARS = 280

#: Verbos definitorios. El grupo 1 es el sujeto y el 2 la definición.
_PATRONES = (
    re.compile(r"^(.{3,80}?)\s+se define como\s+(.{25,})$", re.IGNORECASE),
    re.compile(r"^(.{3,80}?)\s+consiste en\s+(.{25,})$", re.IGNORECASE),
    re.compile(r"^(.{3,80}?)\s+es un[ao]?\s+(.{25,})$", re.IGNORECASE),
    re.compile(r"^(.{3,80}?)\s+son un[ao]?s?\s+(.{25,})$", re.IGNORECASE),
    re.compile(r"^(.{3,80}?)\s+is an?\s+(.{25,})$", re.IGNORECASE),
    re.compile(r"^(.{3,80}?)\s+are\s+(.{25,})$", re.IGNORECASE),
)

_ARTICULOS = ("el ", "la ", "los ", "las ", "un ", "una ", "the ", "a ", "an ")


class ModelClient(Protocol):
    def generate(
        self,
        model: str,
        prompt: str,
        system: str | None = ...,
        options: dict[str, Any] | None = ...,
    ) -> Any: ...


def _frases(texto: str) -> list[str]:
    limpio = re.sub(r"\s+", " ", texto).strip()
    return [f.strip() for f in re.split(r"(?<=[.!?])\s+", limpio) if f.strip()]


def _normalizar_clave(bruto: str) -> str:
    clave = bruto.strip().strip("\"'“”().,;:").lower()
    for articulo in _ARTICULOS:
        if clave.startswith(articulo):
            clave = clave[len(articulo) :]
            break
    return clave.strip()


def _clave_valida(clave: str) -> bool:
    if not clave or len(clave) < 3:
        return False
    return len(clave.split()) <= MAX_KEY_WORDS


#: Nexos que no distinguen un concepto de otro. «control de acceso» y «control
#: acceso» son la misma clave; sin esto, `both` guarda las dos porque un modelo
#: no siempre repite las preposiciones.
_NEXOS = frozenset({"de", "del", "la", "el", "los", "las", "of", "the"})


def _huella(clave: str) -> str:
    return " ".join(p for p in clave.split() if p not in _NEXOS)


def _terminos(texto: str) -> set[str]:
    return {p for p in re.findall(r"[a-záéíóúñ0-9]{4,}", texto.lower())}


def _relevancia(frase: str, pregunta: set[str]) -> int:
    return len(pregunta & _terminos(frase)) if pregunta else 0


def distill_rules(
    texto: str, *, question: str = "", limit: int = MAX_CLAIMS
) -> list[dict[str, str]]:
    """Frases definitorias del texto, sin modelo y siempre igual ante el mismo texto."""
    pregunta = _terminos(question)
    encontradas: list[tuple[int, dict[str, str]]] = []
    vistas: set[str] = set()
    for frase in _frases(texto):
        for patron in _PATRONES:
            match = patron.match(frase)
            if not match:
                continue
            clave = _normalizar_clave(match.group(1))
            valor = re.sub(r"\s+", " ", match.group(2)).strip()[:MAX_VALUE_CHARS]
            if not _clave_valida(clave) or len(valor) < MIN_VALUE_CHARS:
                continue
            if clave in vistas:
                continue
            vistas.add(clave)
            encontradas.append(
                (
                    _relevancia(frase, pregunta),
                    {"key": clave, "value": valor, "extractor": RULE_EXTRACTOR},
                )
            )
            break
    # Lo más pertinente a la pregunta primero; el orden de la página no dice nada.
    encontradas.sort(key=lambda item: item[0], reverse=True)
    return [claim for _, claim in encontradas[:limit]]


def _anclada(valor: str, texto: str) -> bool:
    """¿Está la afirmación sostenida por el texto, o se la inventó el modelo?

    No exige cita literal —un modelo reformula— pero sí que la mayoría de sus
    términos con contenido aparezcan en la fuente. Sin esta comprobación, meter
    un modelo en la cadena de evidencia sería meter una fuente que no se puede
    auditar.
    """
    terminos = _terminos(valor)
    if not terminos:
        return False
    presentes = terminos & _terminos(texto)
    return len(presentes) / len(terminos) >= 0.6


def distill_model(
    texto: str,
    *,
    client: ModelClient,
    model: str,
    question: str = "",
    limit: int = MAX_CLAIMS,
) -> list[dict[str, str]]:
    """Afirmaciones propuestas por un modelo local y **verificadas** contra el texto."""
    # El esquema va por ejemplo y no por nombres de hueco: con
    # `{"key": "sujeto breve", ...}` un modelo de 3B copia literalmente
    # «sujeto breve» como clave y mete el sujeto en el valor. Comprobado contra
    # qwen2.5:3b-instruct — devolvía JSON válido y cero afirmaciones útiles.
    prompt = (
        "Extrae afirmaciones verificables del TEXTO.\n"
        'Responde SOLO un array JSON. Cada objeto lleva "key" (el término del '
        'que se afirma algo, 1 a 4 palabras) y "value" (qué se afirma de él, '
        "frase completa de al menos 25 caracteres).\n"
        'Ejemplo: [{"key": "fotosíntesis", "value": "proceso por el que las '
        'plantas convierten la luz solar en energía química"}]\n'
        f"Máximo {limit} objetos. No inventes nada que no esté en el TEXTO.\n\n"
        f"PREGUNTA: {question}\n\nTEXTO:\n{texto[:6000]}"
    )
    try:
        resultado = client.generate(
            model,
            prompt,
            system="Devuelves únicamente JSON válido, sin explicaciones.",
            options={"temperature": 0.0},
        )
    except Exception:  # noqa: BLE001 — un fallo del modelo no puede tumbar la investigación
        return []

    crudo = str(
        getattr(resultado, "text", "") or getattr(resultado, "response", "") or ""
    )
    match = re.search(r"\[.*\]", crudo, re.DOTALL)
    if not match:
        return []
    try:
        propuestas = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(propuestas, list):
        return []

    claims: list[dict[str, str]] = []
    vistas: set[str] = set()
    for item in propuestas:
        if not isinstance(item, dict):
            continue
        clave = _normalizar_clave(str(item.get("key") or ""))
        valor = re.sub(r"\s+", " ", str(item.get("value") or "")).strip()[
            :MAX_VALUE_CHARS
        ]
        if not _clave_valida(clave) or len(valor) < MIN_VALUE_CHARS:
            continue
        if clave in vistas or not _anclada(valor, texto):
            continue
        vistas.add(clave)
        claims.append({"key": clave, "value": valor, "extractor": MODEL_EXTRACTOR})
        if len(claims) >= limit:
            break
    return claims


def distill_claims(
    texto: str,
    *,
    question: str = "",
    extractor: str = "rules",
    client: ModelClient | None = None,
    model: str = "qwen3:1.7b",
    limit: int = MAX_CLAIMS,
) -> list[dict[str, str]]:
    """Destila afirmaciones con el extractor pedido.

    `both` une los dos y las reglas mandan: si los dos proponen la misma clave,
    se conserva la determinista. Sin cliente de modelo, `model` y `both` caen a
    reglas en vez de fallar — quedarse sin investigación por no tener Ollama
    sería peor que investigar con menos cobertura.
    """
    if not texto.strip():
        return []
    modo = extractor.strip().lower()
    if modo not in {"rules", "model", "both"}:
        raise ValueError(f"extractor no soportado: {extractor}")

    if modo == "rules" or client is None:
        # Sin cliente, `model` y `both` caen a reglas: quedarse sin investigar
        # por no tener Ollama arriba sería peor que investigar con menos
        # cobertura, y las reglas no dependen de nada externo.
        return distill_rules(texto, question=question, limit=limit)

    por_reglas = (
        distill_rules(texto, question=question, limit=limit) if modo == "both" else []
    )
    por_modelo = distill_model(
        texto, client=client, model=model, question=question, limit=limit
    )
    if modo == "model":
        return por_modelo

    claves = {_huella(claim["key"]) for claim in por_reglas}
    combinadas = por_reglas + [c for c in por_modelo if _huella(c["key"]) not in claves]
    return combinadas[:limit]

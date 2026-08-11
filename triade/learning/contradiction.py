"""Detecta que un candidato afirma lo contrario de lo que ya está consolidado.

`consolidate()` tenía gates para casi todo —estado, procedencia, riesgo, usos,
score, evidencia de Measurement Core, rollback obligatorio, constitución,
aislamiento embedding↔evaluación y consejo de verificación— y ninguno para lo
más elemental: que el aprendizaje nuevo contradiga a la memoria estable.

Sin esto, dos hechos incompatibles sobre el mismo sujeto conviven en
`semantic_documents` con estado `stable`, y la recuperación los devuelve a los
dos. Lo que llega al modelo entonces no es memoria sino ruido, y el organismo no
tiene forma de saber cuál de los dos creerse. Un solo dato equivocado
consolidado envenena todas las respuestas posteriores sobre ese sujeto: es el
peor fallo posible de una memoria, porque no se nota.

La comparación reutiliza `extract_target`, el mismo extractor con el que
`knowledge_probe` decide si un candidato es medible. Dos afirmaciones se
contradicen cuando hablan del mismo sujeto —el contenido sin su dato
distintivo— y ese dato distintivo es distinto. No se intenta nada más listo:
un detector semántico difuso produciría falsos positivos que bloquearían
aprendizaje legítimo, y aquí bloquear de más es tan caro como bloquear de menos.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from triade.db import sqlite3
from triade.learning.knowledge_probe import extract_target

#: Cuánto tienen que solaparse los sujetos para considerarlos el mismo. Alto a
#: propósito: el coste de un falso positivo es rechazar un aprendizaje bueno.
MIN_SUBJECT_OVERLAP = 0.8

#: Un sujeto de dos palabras se parece a demasiadas cosas. Por debajo de esto no
#: se afirma contradicción: se deja pasar y que decidan los gates de evidencia.
MIN_SUBJECT_TOKENS = 4


def _normalize(text: str) -> str:
    plain = unicodedata.normalize("NFKD", str(text))
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", plain.lower()).strip()


def subject_of(content: str) -> tuple[str, frozenset[str]]:
    """El sujeto de una afirmación: su contenido sin el dato que afirma.

    «el identificador de mi entorno es ENTORNO_LIMA_4462» y «el identificador de
    mi entorno es ENTORNO_LIMA_9999» tienen el mismo sujeto y distinto dato.
    """
    objetivo = extract_target(content)
    texto = str(content or "")
    if objetivo:
        texto = texto.replace(objetivo, " ")
    normalizado = _normalize(texto)
    return normalizado, frozenset(normalizado.split())


def _overlap(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


@dataclass(frozen=True, slots=True)
class Contradiction:
    document_id: str
    existing_target: str
    candidate_target: str
    subject_overlap: float
    existing_content: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "existing_target": self.existing_target,
            "candidate_target": self.candidate_target,
            "subject_overlap": round(self.subject_overlap, 4),
            "existing_content": self.existing_content,
        }


def find_contradiction(
    db_path: str | Path,
    content: str,
    *,
    exclude_document_ids: frozenset[str] = frozenset(),
) -> Contradiction | None:
    """Busca en la memoria estable una afirmación incompatible con `content`.

    Sólo se comparan documentos `stable`: los `candidate` y `experimental` aún
    no son memoria y contradecirlos no significa nada. Devuelve la primera
    incompatibilidad encontrada, que es cuanto necesita quien va a bloquear.
    """
    objetivo = extract_target(content)
    if not objetivo:
        # Sin dato distintivo no hay nada que contradecir: es exactamente el
        # mismo criterio con el que `knowledge_probe` declara inmedible a un
        # candidato, y por la misma razón.
        return None

    _, tokens = subject_of(content)
    if len(tokens) < MIN_SUBJECT_TOKENS:
        return None

    objetivo_norm = _normalize(objetivo)
    conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        filas = conn.execute(
            "SELECT document_id, content FROM semantic_documents WHERE status = 'stable'"
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        conn.close()

    for fila in filas:
        document_id = str(fila["document_id"])
        if document_id in exclude_document_ids:
            continue
        existente = str(fila["content"] or "")
        objetivo_existente = extract_target(existente)
        if not objetivo_existente:
            continue
        if _normalize(objetivo_existente) == objetivo_norm:
            # Mismo dato: es la misma afirmación, no una contradicción. Si además
            # el sujeto coincide, es un duplicado y de eso se ocupa el upsert por
            # hash de contenido.
            continue
        _, tokens_existente = subject_of(existente)
        solape = _overlap(tokens, tokens_existente)
        if solape >= MIN_SUBJECT_OVERLAP:
            return Contradiction(
                document_id=document_id,
                existing_target=objetivo_existente,
                candidate_target=objetivo,
                subject_overlap=solape,
                existing_content=existente,
            )
    return None

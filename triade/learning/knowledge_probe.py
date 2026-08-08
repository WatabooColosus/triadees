"""Convierte un candidato en una prueba objetiva, o dice que no se puede.

Sin esto, evaluar un candidato exigiría que una persona escribiera a mano la
pregunta y el criterio. Con esto, el worker puede decidir solo si un candidato
es medible — y, sobre todo, **negarse** cuando no lo es.

Un candidato sólo es evaluable si de su contenido puede extraerse un dato
concreto que el modelo no sabría por su cuenta: una etiqueta, un identificador,
un prefijo, un nombre de paso. Si el aprendizaje es una vaguedad, no hay
experimento posible y se declara así, en vez de inventar una métrica.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

#: Un token distintivo: mayúsculas, guiones, dos puntos o dígitos. Las palabras
#: corrientes no sirven — «informe» aparecería igual sin haber aprendido nada.
# Sin `\b` final tras `::`: los dos puntos no son carácter de palabra, así que
# un límite ahí nunca casaría y `WRK::` se perdía.
_DISTINTIVO = re.compile(
    r"(?:\b[A-Z][A-Z0-9]{2,}(?:[-_][A-Z0-9]+)+\b|\b[A-Z]{2,}::|\b[a-z]+_[a-z_]+\b)"
)

#: Identificadores de andamiaje: aparecen en todo el repositorio, en los propios
#: enunciados y en el vocabulario común de cualquier modelo. No cumplen el
#: requisito que este módulo declara —«un dato concreto que el modelo no sabría
#: por su cuenta»— y por eso no pueden ser el hueco de una pregunta.
#:
#: Medido el 2026-08-03: los candidatos con más uso real del sistema (hasta 44
#: usos) extraían `mission_id` como dato distintivo, y la pregunta resultante era
#: «…debe evaluarse con evidencia local trazable por ___ y run_ref…». La
#: respuesta estaba implícita en el propio enunciado, así que el brazo de control
#: acertaba 5 de 5 sin haber aprendido nada: `control 1.0, tratamiento 1.0,
#: delta 0.0 -> neutral`, siempre. No eran candidatos malos, era una sonda
#: inválida — el mismo patrón que la contaminación del control de agosto, por
#: otra puerta.
_ANDAMIAJE = frozenset(
    {
        # Medido el 2026-08-08: 230 de 250 candidatos conversacionales extraían
        # `verification_status`, y el 96% de sus evidencias salía `neutral` —la
        # misma firma que `mission_id` en agosto: control 1.0, tratamiento 1.0,
        # delta 0.0—. Es un nombre de campo del propio registro de run, no un
        # hecho aprendido: la pregunta lleva la respuesta dentro. Los dos únicos
        # `improved` de esa población salieron de targets que sí afirman algo
        # del mundo (`recall_is_selective_not_total`, `identity_continuous`),
        # ahogados 100 a 1 por transcripciones.
        "verification_status",
        "mission_id",
        "run_ref",
        "run_id",
        "source_ref",
        "candidate_id",
        "task_type",
        "task_id",
        "goal_id",
        "node_id",
        "evidence_ref",
        "db_path",
        "created_at",
        "updated_at",
        "parent_id",
        "step_id",
        "neuron_id",
        "report_id",
        "risk_level",
        "source_type",
    }
)

_PREGUNTAS = {
    "preference": "Según la preferencia registrada, {sujeto}",
    "fact": "Según lo registrado, {sujeto}",
    "correction": "Según la corrección registrada, {sujeto}",
    "procedure": "Según el procedimiento registrado, {sujeto}",
}


def _normalize(text: str) -> str:
    plain = unicodedata.normalize("NFKD", str(text))
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", plain.lower()).strip()


@dataclass
class KnowledgeProbe:
    """Una pregunta y un criterio determinista para un candidato concreto."""

    candidate_id: str
    question: str
    expected: str
    evaluator: Callable[[str], bool]


def extract_target(content: str) -> str | None:
    """Devuelve el dato distintivo del contenido, si lo hay.

    Se prefiere el token más largo: entre `WRK` y `VEREDICTO-TRIADE`, el
    segundo es mucho más difícil de acertar por casualidad.

    Los identificadores de andamiaje se descartan aunque sean el único
    candidato: preguntar por `mission_id` no mide aprendizaje, mide si el modelo
    conoce el vocabulario del repositorio —y lo conoce—. Sin dato distintivo real
    el candidato es inmedible, que es una respuesta legítima de este módulo.
    """
    texto = str(content or "")
    candidatos = [
        token for token in _DISTINTIVO.findall(texto) if token not in _ANDAMIAJE
    ]
    if not candidatos:
        return None
    return max(candidatos, key=len)


def build_probe(db_path: str | Path, candidate_id: str) -> KnowledgeProbe | None:
    """Construye la prueba, o `None` si el candidato no es medible."""
    conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        fila = conn.execute(
            "SELECT content, verification_notes FROM learning_queue"
            " WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()

    if fila is None:
        return None

    contenido = str(fila["content"] or "")
    objetivo = extract_target(contenido)
    if not objetivo:
        return None

    tipo = "preference"
    notas = str(fila["verification_notes"] or "")
    for candidato_tipo in _PREGUNTAS:
        if f'"type": "{candidato_tipo}"' in notas or f'"{candidato_tipo}"' in notas:
            tipo = candidato_tipo
            break

    # La pregunta no puede contener la respuesta: si la nombrara, el control
    # acertaría solo y la medición no mediría nada. Por eso se elimina el
    # objetivo del texto que se usa para preguntar.
    sujeto = contenido.replace(objetivo, "___").rstrip(". ")
    plantilla = _PREGUNTAS.get(tipo, _PREGUNTAS["fact"])
    question = (
        f"{plantilla.format(sujeto=f'¿qué va en el hueco de: «{sujeto}»?')} "
        "Responde solo con el valor exacto."
    )

    objetivo_norm = _normalize(objetivo)

    def evaluator(respuesta: str) -> bool:
        return bool(objetivo_norm) and objetivo_norm in _normalize(respuesta)

    return KnowledgeProbe(
        candidate_id=candidate_id,
        question=question,
        expected=objetivo,
        evaluator=evaluator,
    )

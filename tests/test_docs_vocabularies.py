"""La documentación no puede nombrar task types ni estados que no existen.

Extiende el gate de drift a los dos vocabularios que más se han copiado —y más
se han quedado atrás— en este repositorio: los tipos de tarea de los workers y
los estados de la cola y del aprendizaje.

Un documento que nombra un `task_type` retirado o un estado que ningún módulo
escribe describe un sistema que no existe. Y como los vocabularios tienen dueño
declarado, la comprobación es exacta: no hay que interpretar prosa, basta con
comparar contra la fuente.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.test_docs_no_drift import _docs_actuales
from triade.learning.pipeline import LearningPipeline
from triade.runtime.task_status import ALL_STATES
from triade.workers.contracts import WORKER_TASK_TYPES

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Sólo se juzgan los nombres que aparecen entre comillas invertidas: es la
#: forma en que estos documentos citan un identificador. Nombrarlo en prosa
#: corriente no es afirmar que exista.
_CITADO = re.compile(r"`([a-z][a-z0-9_]{4,})`")


def _citados_en_docs() -> dict[str, list[str]]:
    encontrados: dict[str, list[str]] = {}
    for doc in _docs_actuales():
        for nombre in _CITADO.findall(doc.read_text(encoding="utf-8")):
            encontrados.setdefault(nombre, []).append(
                str(doc.relative_to(REPO_ROOT))
            )
    return encontrados


def test_los_task_types_citados_existen_en_el_contrato() -> None:
    """`WORKER_TASK_TYPES` es el dueño; la documentación sólo lo refleja."""
    citados = _citados_en_docs()
    # Un nombre cuenta como task type si termina en algo que sólo usan ellos, o
    # si ya está en el contrato. Así no se juzga cualquier palabra con guiones.
    sospechosos = {
        n: docs
        for n, docs in citados.items()
        if n.endswith(("_review", "_scan", "_check", "_cycle", "_observation"))
    }
    inexistentes = {
        n: docs for n, docs in sospechosos.items() if n not in WORKER_TASK_TYPES
    }

    assert not inexistentes, (
        "documentación que cita task types fuera de WORKER_TASK_TYPES:\n"
        + "\n".join(f"  {n} ← {', '.join(d)}" for n, d in sorted(inexistentes.items()))
    )


def test_los_estados_citados_pertenecen_a_un_vocabulario_con_dueno() -> None:
    """Los estados los declaran `task_status` y `LearningPipeline`, nadie más.

    Esta sesión encontró tres copias a mano de `CONSOLIDATABLE_STATES` y dos del
    vocabulario de fuentes sin aprendizaje. La documentación es el cuarto sitio
    donde una copia se queda atrás sin que nadie lo note.
    """
    vocabulario = set(ALL_STATES) | set(LearningPipeline.CONSOLIDATABLE_STATES) | {
        "stable",
        "candidate",
        "evaluated",
        "quarantined",
        "regressed",
        "experimental",
    }
    #: Estados que la documentación menciona y ningún vocabulario declara. Se
    #: detectan por su forma: participios y sufijos de estado.
    citados = _citados_en_docs()
    sospechosos = {
        n: docs
        for n, docs in citados.items()
        if n.endswith(("_verified", "_checked", "_wait", "_letter"))
    }
    huerfanos = {n: docs for n, docs in sospechosos.items() if n not in vocabulario}

    assert not huerfanos, (
        "documentación que cita estados fuera del vocabulario declarado:\n"
        + "\n".join(f"  {n} ← {', '.join(d)}" for n, d in sorted(huerfanos.items()))
    )

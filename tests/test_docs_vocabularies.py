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
from triade.observability.alias_debt import SIMILARITY_THRESHOLD, similarity
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
            encontrados.setdefault(nombre, []).append(str(doc.relative_to(REPO_ROOT)))
    return encontrados


def test_ningun_documento_cita_el_gemelo_muerto_de_un_task_type() -> None:
    """Un nombre casi igual a un task type real, y que no existe, es el fallo.

    La primera versión de esta prueba adivinaba por sufijo —`_review`, `_cycle`,
    `_scan`— y marcaba también tablas (`metabolic_cycle`), funciones
    (`run_neuron_nutrition_cycle`) y campos (`next_review`). Más ruido que
    señal, y encima adivinando por la forma del nombre: exactamente el error que
    persigue `alias_debt`.

    Se compara contra el contrato con la misma maquinaria de similitud que usa
    ese detector, en vez de inventar una nueva. La separación es limpia sobre
    los casos reales del repositorio:

        memory_consolidation_review  0.67  ← gemelo muerto, se marca
        run_neuron_nutrition_cycle   0.50  ← función, no se marca
        metabolic_cycle              0.33  ← tabla
        next_review                  0.33  ← campo

    Encontró `memory_consolidation_review` en ocho documentos que se presentaban
    como estado actual. `alias_debt` documenta ese par exacto como su ejemplo
    fundacional, y llevaba meses vivo en la documentación porque ese detector
    mira código y SQL, no documentos.
    """
    # Un nombre que es una tabla real no es el gemelo muerto de un task type,
    # aunque comparta segmentos: `learning_evidence` se parece a
    # `learning_evidence_generation` porque la tarea escribe esa tabla. La
    # fuente es `schemas.sql`, que está en el repositorio y por tanto disponible
    # en CI — la base viva no lo está.
    esquema = (REPO_ROOT / "triade/memory/schemas.sql").read_text(encoding="utf-8")
    tablas = set(re.findall(r"CREATE TABLE(?: IF NOT EXISTS)? (\w+)", esquema))

    gemelos: list[str] = []
    for nombre, docs in _citados_en_docs().items():
        if nombre in WORKER_TASK_TYPES or nombre in tablas:
            continue
        parecido, real = max(
            ((similarity(nombre, t), t) for t in WORKER_TASK_TYPES), default=(0.0, "")
        )
        if parecido > SIMILARITY_THRESHOLD:
            gemelos.append(
                f"  {nombre} (≈{parecido:.2f} de {real}) ← {', '.join(docs)}"
            )

    assert not gemelos, (
        "documentación que cita el gemelo muerto de un task type real:\n"
        + "\n".join(sorted(gemelos))
    )


def test_los_estados_citados_pertenecen_a_un_vocabulario_con_dueno() -> None:
    """Los estados los declaran `task_status` y `LearningPipeline`, nadie más.

    Esta sesión encontró tres copias a mano de `CONSOLIDATABLE_STATES` y dos del
    vocabulario de fuentes sin aprendizaje. La documentación es el cuarto sitio
    donde una copia se queda atrás sin que nadie lo note.
    """
    vocabulario = (
        set(ALL_STATES)
        | set(LearningPipeline.CONSOLIDATABLE_STATES)
        | {
            "stable",
            "candidate",
            "evaluated",
            "quarantined",
            "regressed",
            "experimental",
        }
    )
    #: Estados que la documentación menciona y ningún vocabulario declara. Se
    #: detectan por su forma: participios y sufijos de estado.
    citados = _citados_en_docs()
    sospechosos = {
        n: docs
        for n, docs in citados.items()
        # Un sujeto en plural es un contador, no un estado: `candidates_verified`
        # cuenta candidatos verificados, no describe en qué estado está uno.
        if n.endswith(("_verified", "_checked", "_wait", "_letter"))
        and not n.split("_")[0].endswith("s")
    }
    huerfanos = {n: docs for n, docs in sospechosos.items() if n not in vocabulario}

    assert not huerfanos, (
        "documentación que cita estados fuera del vocabulario declarado:\n"
        + "\n".join(f"  {n} ← {', '.join(d)}" for n, d in sorted(huerfanos.items()))
    )

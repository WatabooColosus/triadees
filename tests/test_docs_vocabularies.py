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
            encontrados.setdefault(nombre, []).append(str(doc.relative_to(REPO_ROOT)))
    return encontrados


#: El documento afirma que lo citado es un task type: lo dice la propia línea o
#: el encabezado bajo el que vive. No se adivina por la forma del nombre — eso se
#: probó dos veces y marcaba tablas, módulos y campos, porque comparten
#: vocabulario con la tarea que los usa.
_AFIRMA_TASK_TYPE = re.compile(r"task[ _]type|tipos? de tarea", re.IGNORECASE)


def _task_types_afirmados(texto: str) -> set[str]:
    """Identificadores que el texto presenta como tipos de tarea."""
    afirmados: set[str] = set()
    encabezado_afirma = False
    for linea in texto.splitlines():
        if linea.startswith(("#", "|---")):
            encabezado_afirma = bool(_AFIRMA_TASK_TYPE.search(linea))
        if encabezado_afirma or _AFIRMA_TASK_TYPE.search(linea):
            afirmados.update(_CITADO.findall(linea))
    return afirmados


def test_los_task_types_afirmados_existen_en_el_contrato() -> None:
    """Si un documento dice que algo es un task type, tiene que serlo.

    Dos intentos anteriores fallaron por adivinar: primero por sufijo
    (`_review`, `_cycle`), luego por parecido con `alias_debt.similarity`. Los
    dos marcaban tablas, módulos y campos —`metabolic_cycle`, `self_improvement`,
    `neuron_formation_pipeline`— porque comparten vocabulario con la tarea que
    los implementa. Ni el umbral ni un inventario de identificadores lo
    arreglaban: el signo estaba mal elegido.

    Este mira lo que el documento **afirma**, no a qué se parece el nombre. Es
    la diferencia entre acusar por la forma y acusar por lo dicho, que es
    justamente la leccion que `alias_debt` documenta sobre sí mismo.
    """
    inexistentes: list[str] = []
    for doc in _docs_actuales():
        texto = doc.read_text(encoding="utf-8")
        for nombre in sorted(_task_types_afirmados(texto)):
            # Sólo se juzga lo que se parece a un identificador de tarea; el
            # ruido de la línea (palabras sueltas entre comillas) no se acusa.
            # Nombrar el concepto no es afirmar una instancia: `task_type` es la
            # columna, `task_types_never_executed` una categoría de deuda y
            # `test_…` una prueba. Y un módulo citado en una línea que habla de
            # tareas sigue siendo un módulo.
            if (
                "_" not in nombre
                or nombre in WORKER_TASK_TYPES
                or "task_type" in nombre
                or nombre.startswith("test_")
                or (REPO_ROOT / "triade/workers" / f"{nombre}.py").exists()
            ):
                continue
            inexistentes.append(f"  {nombre} ← {doc.relative_to(REPO_ROOT)}")

    assert not inexistentes, (
        "documentación que presenta como task type algo que no está en "
        "WORKER_TASK_TYPES:\n" + "\n".join(sorted(set(inexistentes)))
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


def test_la_comprobacion_detecta_una_reintroduccion(tmp_path, monkeypatch) -> None:
    """Sin esto, un gate que pasa no demuestra nada.

    `memory_consolidation_review` vivió meses en ocho documentos. La prueba de
    que este gate lo habría cazado es reintroducirlo y ver que salta.
    """
    doc = tmp_path / "FALSO.md"
    doc.write_text(
        "# Tipos de tarea\n\n- `memory_consolidation_review`: consolida memoria\n",
        encoding="utf-8",
    )

    afirmados = _task_types_afirmados(doc.read_text(encoding="utf-8"))

    assert "memory_consolidation_review" in afirmados
    assert "memory_consolidation_review" not in WORKER_TASK_TYPES, (
        "si esto falla, el tipo volvió al contrato y la prueba pierde sentido"
    )

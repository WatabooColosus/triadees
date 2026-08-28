"""El sensor: un run terminado deja constancia durable de su experiencia.

`_learning_candidate_generation` existía completo —handler, tipo de tarea,
pruebas— y nadie lo encolaba nunca. Medido sobre producción el 2026-08-01: 98
runs de conversación en 24 h y **cero** tareas de generación de candidatos. Las
etapas posteriores sí corrían, pero sobre candidatos sembrados por scripts.

Conectado el nervio, apareció el defecto siguiente: este módulo se había
convertido en la **autoridad** de aprendizaje. Encolaba la extracción
directamente, sin `goal_id`, y con eso decidía por su cuenta que había algo que
aprender y cuál era la primera etapa. Medido el 2026-08-28 sobre la base viva:
737 tareas de extracción, **ninguna** enlazada a un objetivo, y por tanto
ninguna que Central llegara a ver —`GoalOrchestrator.record_task_result` sale en
la primera línea si falta el `goal_id`—.

Aquí ya no se decide nada. Se **observa**: se escribe una observación durable y
se sale. Quien clasifica, consulta lo que ya se sabe, decide si merece la pena
aprender y planifica las etapas es `CentralLearningPlanner`, y lo hace después,
dentro de un worker.

Tres reglas gobiernan este módulo:

- **Aprender nunca puede retrasar una conversación.** Aquí se escribe una fila
  y se sale. Nada de inferencia, nada de red, nada de esperas.
- **Aprender nunca puede romper una conversación.** Si la cola no se puede
  escribir, el usuario recibe su respuesta igual y el fallo se devuelve dicho,
  no tragado.
- **Observar no es decidir.** Este módulo no elige etapa ni crea saber.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from triade.core.runtime_scope import source_alimenta_aprendizaje
from triade.db import sqlite3
from triade.runtime.task_leases import AutonomousTaskStore

#: Campos que la observación consume hoy de verdad —los mismos que
#: `_learning_candidate_generation` recibe después de que Central planifique—.
#: El resto del payload viaja como contexto para las fases siguientes (tipos de
#: conocimiento, control/tratamiento), pero estos cuatro son el contrato.
CONSUMED_FIELDS = ("source_run_id", "message", "role", "domain", "intent")

#: El tipo de tarea que abre el ciclo. No es una etapa de aprendizaje: es la
#: entrada a Central.
OBSERVATION_TASK_TYPE = "central_learning_observation"


#: Valores que cuentan como «encendido» en la variable.
_ENCENDIDO = frozenset({"1", "true", "yes", "on"})


def post_run_learning_enabled() -> bool:
    """`TRIADE_POST_RUN_LEARNING`. Encendido en producción, apagado en pruebas.

    Estuvo apagado por defecto a propósito: encender el aprendizaje automático
    sobre conversaciones reales era una decisión, no un efecto colateral de
    desplegar. Esa decisión ya se tomó —está en `.env` desde el 2026-08-27— y
    dejar el defecto del código en `0` convertía el aprendizaje continuo de
    Tríade en algo que depende de que alguien se acuerde de exportar una
    variable. Un reinicio con el `.env` sin cargar, un worker lanzado a mano, un
    contenedor sin ese fichero: en los tres casos el organismo deja de aprender
    y nada lo dice.

    El defecto se invierte, pero **no** para las pruebas. Un banco de pruebas no
    es una experiencia humana: cuando el aprendizaje se encendía en la suite,
    43 candidatos extraían `TRIADA_VIVA` —la frase del propio test— como dato
    distintivo. `is_test_runtime()` es la misma frontera que ya usan
    `runner_preflight` y `isolated_runtime_paths`, no una nueva.

    Una variable puesta explícitamente manda siempre, en los dos sentidos:
    `TRIADE_POST_RUN_LEARNING=0` apaga aunque sea producción, y `=1` enciende
    aunque sea una prueba que quiera ejercitar el circuito.
    """
    crudo = os.environ.get("TRIADE_POST_RUN_LEARNING")
    if crudo is not None and str(crudo).strip():
        return str(crudo).strip().lower() in _ENCENDIDO
    from triade.core.runtime_scope import is_test_runtime

    return not is_test_runtime()


def schedule_learning_from_run(
    db_path: str | Path,
    *,
    run_id: str,
    message: str,
    response: str,
    domain: str = "conversation",
    role: str = "user",
    intent: str = "conversation",
    model_id: str | None = None,
    neuron_id: str | None = None,
    tools_used: list[str] | None = None,
    outcome: str | None = None,
    safety_flags: list[str] | None = None,
    timestamp: str | None = None,
    enabled: bool | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Encola la extracción de aprendizaje de un run ya cerrado.

    Devuelve siempre un diccionario; nunca lanza. Quien llama está en el camino
    de respuesta al usuario y no puede permitirse una excepción por algo
    opcional.
    """
    if enabled is None:
        enabled = post_run_learning_enabled()
    if not enabled:
        return {"scheduled": False, "reason": "post_run_learning_disabled"}
    if source is not None and not source_alimenta_aprendizaje(source):
        # Una certificación no es una conversación. Sin esto, los runs de prueba
        # encolaban aprendizaje y 43 candidatos extraían `TRIADA_VIVA` —la frase
        # del propio test— como dato distintivo.
        return {"scheduled": False, "reason": f"source_sin_aprendizaje:{source}"}
    if not str(run_id or "").strip():
        return {"scheduled": False, "reason": "empty_run_id"}
    if not str(message or "").strip():
        # El handler lo rechazaría igual por `payload_incompleto`. Mejor no
        # encolar ruido que luego alguien tiene que barrer.
        return {"scheduled": False, "reason": "empty_message"}

    payload: dict[str, Any] = {
        "source_run_id": run_id,
        "message": message,
        "role": role,
        "domain": domain,
        "intent": intent,
        "response": response,
        "model_id": model_id,
        "neuron_id": neuron_id,
        "tools_used": list(tools_used or []),
        "outcome": outcome,
        "safety_flags": list(safety_flags or []),
        "timestamp": timestamp,
    }
    try:
        store = AutonomousTaskStore(db_path)
        # Clave de idempotencia por run: reintentar el cierre de un run no puede
        # duplicar su aprendizaje.
        # Prioridad 25, no 70. En `autonomous_tasks` gana el número **bajo**, y
        # 70 era el peor valor de los diecinueve tipos de tarea del sistema —el
        # siguiente peor es `research_curriculum` con 45 y todo lo demás está en
        # 35 o menos—. Justo la tarea que convierte una conversación en saber
        # iba la última de la cola.
        #
        # `claim()` envejece un punto por minuto (`priority - min(100, edad)`),
        # así que con 70 hacían falta ~60 minutos para superar a un `pulse_check`
        # recién creado, y de esos entran unos tres por minuto. Medido sobre los
        # últimos siete días de la base viva: mediana de 124 s y máximo de 5.682 s
        # —95 minutos—, contra 5 s de mediana en `pulse_check` y 1 s en el resto
        # de las etapas de aprendizaje.
        #
        # 25 no adelanta a nada que importe: sigue por detrás del latido (10),
        # la copia cifrada (4), la deduplicación (6), la bodega (12), la
        # gobernanza semántica (13) y la educación neuronal (20). Sólo deja de
        # ser un caso aparte. La regla de que aprender no puede retrasar una
        # conversación se sostiene igual: aquí sólo se escribe una fila, y el
        # trabajo ocurre después en el worker.
        task = store.enqueue(
            OBSERVATION_TASK_TYPE,
            payload,
            idempotency_key=f"post-run-learning:{run_id}",
            priority=25,
        )
    except (sqlite3.Error, OSError, ValueError) as exc:
        # Se devuelve dicho, no tragado. `except Exception: pass` aquí sería
        # perder en silencio todo el aprendizaje del organismo.
        return {
            "scheduled": False,
            "reason": "enqueue_failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "scheduled": True,
        "task_id": task.get("task_id"),
        "run_id": run_id,
        "domain": domain,
    }

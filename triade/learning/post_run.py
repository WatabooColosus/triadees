"""El nervio que faltaba: un run terminado encola su propio aprendizaje.

`_learning_candidate_generation` existía completo —handler, tipo de tarea,
pruebas— y nadie lo encolaba nunca. Medido sobre producción el 2026-08-01: 98
runs de conversación en 24 h y **cero** tareas de generación de candidatos. Las
etapas posteriores sí corrían, pero sobre candidatos sembrados por scripts.

Dos reglas gobiernan este módulo:

- **Aprender nunca puede retrasar una conversación.** Aquí se escribe una fila
  y se sale. Nada de inferencia, nada de red, nada de esperas.
- **Aprender nunca puede romper una conversación.** Si la cola no se puede
  escribir, el usuario recibe su respuesta igual y el fallo se devuelve dicho,
  no tragado.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from triade.core.runtime_scope import source_alimenta_aprendizaje
from triade.runtime.task_leases import AutonomousTaskStore

#: Campos que `_learning_candidate_generation` consume hoy de verdad. El resto
#: del payload viaja como contexto para las fases siguientes (tipos de
#: conocimiento, control/tratamiento), pero estos cuatro son el contrato.
CONSUMED_FIELDS = ("source_run_id", "message", "role", "domain")


def post_run_learning_enabled() -> bool:
    """`TRIADE_POST_RUN_LEARNING`, apagado por defecto.

    Se conecta el nervio pero no se enciende solo: encender el aprendizaje
    automático sobre conversaciones reales es una decisión, no un efecto
    colateral de desplegar. Hasta ahora esta variable se reportaba en
    `Runner.doctor()` y en `/api/runtime/build` sin que nadie la leyera para
    actuar — una bandera que anunciaba una capacidad inexistente.
    """
    return str(os.environ.get("TRIADE_POST_RUN_LEARNING", "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def schedule_learning_from_run(
    db_path: str | Path,
    *,
    run_id: str,
    message: str,
    response: str,
    domain: str = "conversation",
    role: str = "user",
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
        task = store.enqueue(
            "learning_candidate_generation",
            payload,
            idempotency_key=f"post-run-learning:{run_id}",
            priority=70,
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

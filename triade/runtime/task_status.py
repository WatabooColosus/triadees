"""Vocabulario único de estados de tarea de la cola autónoma.

Este vocabulario ya existía —completo y correcto— dentro de `task_leases.py`,
que es quien escribe los estados. El problema no era que faltara: era que nadie
lo importaba. Media docena de módulos redeclaraban el mismo concepto a mano, y
al hacerlo divergían:

===========================================  ====================================
Copia encontrada                             En qué se apartaba
===========================================  ====================================
`workers/contracts.py::TERMINAL_TASK_STATUSES`  se dejaba `observed` y
                                             `dead_letter` fuera de «terminal».
                                             En producción eso son 327 filas —
                                             el 7 % de la cola— tratadas como si
                                             siguieran vivas.
`learning/doctor.py::ACTIVE_STATUSES`        se dejaba `deferred` y
                                             `completion_uncertain` fuera de
                                             «activo»: una tarea diferida era
                                             invisible para el doctor y visible
                                             para el planificador.
`runtime/service_health.py`                  partía lo activo en
                                             `ELIGIBLE`/`IN_FLIGHT` con un
                                             `claimed` que la cola v2 no escribe.
`runtime/execution_result.py`                repetía `TERMINAL_FAILURE` literal.
`workers/worker_loop.py`                     lo repetía otra vez, en línea.
`os/event_engine.py`, `os/neuron_scheduler.py`  listaban siete estados a mano en
                                             SQL, sin `completion_uncertain`.
===========================================  ====================================

Un vocabulario duplicado no falla al duplicarse: falla cuando alguien añade un
estado. `completion_uncertain` y `deferred` se añadieron aquí y las copias no se
enteraron, que es exactamente por qué una auditoría puede contar la misma cola
dos veces y obtener dos respuestas.

Regla: **quien escribe el estado manda**. Estos nombres son los que persiste
`AutonomousTaskStore`; cualquier otro módulo los importa, no los reescribe.
"""

from __future__ import annotations

#: Tarea todavía en juego: aún puede cambiar de estado sin intervención.
ACTIVE: frozenset[str] = frozenset(
    {
        "pending",
        "queued",
        "leased",
        "running",
        "retry_wait",
        "recovered",
        "deferred",
        # Se ejecutó pero no se pudo probar el efecto. Sigue viva a propósito:
        # darla por terminada sería afirmar un resultado que nadie verificó.
        "completion_uncertain",
    }
)

#: Terminó e hizo lo que se le pidió.
TERMINAL_SUCCESS: frozenset[str] = frozenset({"completed"})

#: Terminó sin ejecutar, y eso **no** es un fallo. `observed` es el caso
#: frecuente: el handler miró y decidió que no tocaba actuar.
TERMINAL_NON_SUCCESS: frozenset[str] = frozenset(
    {"blocked", "skipped", "dry_run", "observed", "cancelled"}
)

#: Terminó mal. `lease_lost` y `timeout` cuentan como fallo aunque el handler
#: no llegara a devolver nada: no saber cómo acabó no es haber acabado bien.
TERMINAL_FAILURE: frozenset[str] = frozenset(
    {"failed", "dead_letter", "timeout", "lease_lost"}
)

#: Terminó, del modo que sea. No volverá a moverse sola.
TERMINAL: frozenset[str] = TERMINAL_SUCCESS | TERMINAL_NON_SUCCESS | TERMINAL_FAILURE

#: Estados que la cola escribe. Cualquier otro valor es un error de escritura.
ALL_STATES: frozenset[str] = ACTIVE | TERMINAL

#: Estados en los que la tarea ya está en manos de un worker. Se separa de
#: `ACTIVE` porque una cola con trabajo esperando y una con trabajo en curso son
#: dos situaciones distintas para un sensor de salud.
IN_FLIGHT: frozenset[str] = frozenset({"leased", "running", "completion_uncertain"})

#: Estados en los que la tarea espera a que alguien la tome.
ELIGIBLE: frozenset[str] = ACTIVE - IN_FLIGHT


def is_terminal(status: str) -> bool:
    """¿La tarea terminó, del modo que sea?"""
    return status in TERMINAL


def is_active(status: str) -> bool:
    """¿La tarea todavía puede moverse sola?"""
    return status in ACTIVE


def is_failure(status: str) -> bool:
    """¿Terminó mal? Incluye los finales sin veredicto (`timeout`, `lease_lost`)."""
    return status in TERMINAL_FAILURE


def sql_placeholders(states: frozenset[str]) -> tuple[str, tuple[str, ...]]:
    """Devuelve `('?,?,?', (…))` para un `IN (...)` sin listar estados a mano.

    Se ordena para que la consulta sea estable entre ejecuciones: un `IN` que
    cambia de orden cada arranque hace ilegibles los diffs de logs y los planes
    de consulta.
    """
    ordenados = tuple(sorted(states))
    return ",".join("?" * len(ordenados)), ordenados

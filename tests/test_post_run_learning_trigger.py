"""Todo run terminado debe poder generar aprendizaje por sí solo.

Medido sobre la base de producción el 2026-08-01:

    runs de conversación en 24 h           : 98
    tareas `learning_candidate_generation` :  0   (ninguna, nunca)

`_learning_candidate_generation` está escrito, probado y registrado en
`WORKER_TASK_TYPES`… y **nadie lo encola jamás**. `run_completed` no existe en
el código. Es un órgano completo sin nervio que lo active: las etapas
posteriores (evidencia, deduplicación, revisión) sí corren, pero sobre
candidatos que llegaron por scripts, no por conversaciones reales.

Y hay un segundo cable suelto: `TRIADE_POST_RUN_LEARNING` sólo aparece en
`Runner.doctor()` y en `/api/runtime/build`. Se **reporta** como capacidad y no
se actúa nunca.

Aprender no puede retrasar una conversación, así que esto encola y se aparta:
una fila, con clave de idempotencia por run, y jamás una excepción que rompa la
respuesta al usuario.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.learning.post_run import schedule_learning_from_run
from triade.runtime.task_leases import AutonomousTaskStore


def _tasks(db: Path) -> list[dict]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        return [
            dict(r)
            for r in con.execute(
                "SELECT task_type, status, payload_json, idempotency_key FROM autonomous_tasks"
            )
        ]
    finally:
        con.close()


def test_a_finished_run_enqueues_its_own_learning(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    AutonomousTaskStore(db)

    out = schedule_learning_from_run(
        db,
        run_id="run-1",
        message="prefiero que me respondas en euros, no en dólares",
        response="Anotado.",
        domain="conversation",
        enabled=True,
    )

    assert out["scheduled"] is True, out
    filas = _tasks(db)
    assert len(filas) == 1, filas
    assert filas[0]["task_type"] == "learning_candidate_generation"
    assert '"source_run_id": "run-1"' in filas[0]["payload_json"]
    assert "euros" in filas[0]["payload_json"]


def test_the_same_run_never_enqueues_twice(tmp_path: Path) -> None:
    """Idempotente por run: reintentar el cierre no duplica aprendizaje."""
    db = tmp_path / "triade.db"
    AutonomousTaskStore(db)
    for _ in range(3):
        schedule_learning_from_run(
            db, run_id="run-2", message="hola", response="hola", enabled=True
        )
    assert len(_tasks(db)) == 1


def test_disabled_flag_schedules_nothing(tmp_path: Path) -> None:
    """`TRIADE_POST_RUN_LEARNING` apagado significa apagado, no 'a veces'."""
    db = tmp_path / "triade.db"
    AutonomousTaskStore(db)

    out = schedule_learning_from_run(
        db, run_id="run-3", message="hola", response="hola", enabled=False
    )

    assert out["scheduled"] is False
    assert out["reason"] == "post_run_learning_disabled"
    assert _tasks(db) == []


def test_an_empty_message_is_not_worth_learning(tmp_path: Path) -> None:
    """Sin mensaje no hay experiencia que extraer. El handler lo rechazaría
    igual; mejor no encolar ruido que luego hay que barrer."""
    db = tmp_path / "triade.db"
    AutonomousTaskStore(db)

    out = schedule_learning_from_run(
        db, run_id="run-4", message="   ", response="algo", enabled=True
    )

    assert out["scheduled"] is False
    assert out["reason"] == "empty_message"
    assert _tasks(db) == []


def test_a_broken_queue_never_breaks_the_conversation(tmp_path: Path) -> None:
    """Aprender es opcional. Responder no.

    Si la cola no se puede escribir, el usuario recibe su respuesta igual y el
    fallo queda dicho — no tragado. Sin `except Exception: pass`.
    """
    db = tmp_path / "no" / "existe" / "triade.db"

    out = schedule_learning_from_run(
        db, run_id="run-5", message="hola", response="hola", enabled=True
    )

    assert out["scheduled"] is False
    assert out["reason"] == "enqueue_failed"
    assert out["error"], "el fallo se tragó en silencio"


def test_the_payload_carries_what_the_handler_consumes(tmp_path: Path) -> None:
    """El contrato real del handler: `source_run_id`, `message`, `role`,
    `domain`. El resto viaja como contexto para las fases siguientes, pero esos
    cuatro no pueden faltar."""
    db = tmp_path / "triade.db"
    AutonomousTaskStore(db)
    schedule_learning_from_run(
        db,
        run_id="run-6",
        message="usa siempre tabla para comparar",
        response="ok",
        domain="formato",
        role="user",
        enabled=True,
    )
    import json

    payload = json.loads(_tasks(db)[0]["payload_json"])
    for campo in ("source_run_id", "message", "role", "domain"):
        assert payload.get(campo), f"falta {campo} en {payload}"
    assert payload["domain"] == "formato"

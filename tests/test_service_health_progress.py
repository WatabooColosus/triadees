"""La salud se mide por progreso, y sobre la cola que de verdad existe.

`ServiceHealth.inspect()` leía `worker_tasks` para decidir si la cola avanza.
Esa tabla está **retirada por trigger** desde `019_legacy_retirement.sql`
(`legacy_worker_task_writes_disabled`) y no recibe una fila desde el
2026-07-29. O sea: la señal que debía detectar un organismo atascado miraba un
cadáver.

Consecuencias medibles, y las dos malas:

- con trabajo real encolado y sin avanzar, `inspect()` no dice `stalled`,
  porque la cola que mira está vacía para siempre;
- sin ningún trabajo, tampoco sabía decir `idle` — devolvía `healthy`, que es
  cierto pero no informa: "sano y sin nada que hacer" y "sano y trabajando" no
  son el mismo estado para quien vigila un sistema 24/7.

Un PID vivo no es un run vivo, y un HTTP 200 no es progreso. Una cola vacía
tampoco es una cola sana si la cola de verdad está en otro sitio.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.runtime.service_health import ServiceHealth

_OLLAMA_OK = {"ollama_ok": True}


def _db(tmp_path: Path) -> Path:
    """Base mínima con la cola viva y la heredada, como en producción."""
    db = tmp_path / "triade.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE autonomous_tasks (
            task_id TEXT PRIMARY KEY, task_type TEXT, status TEXT,
            created_at TEXT, updated_at TEXT, worker_id TEXT,
            lease_expires_at TEXT, retry_after TEXT
        );
        CREATE TABLE worker_tasks (
            id INTEGER PRIMARY KEY, task_type TEXT, status TEXT, created_at TEXT
        );
        CREATE TABLE worker_runs (
            id INTEGER PRIMARY KEY, run_ref TEXT, status TEXT,
            started_at TEXT, finished_at TEXT
        );
        CREATE TABLE live_runtime_heartbeat (updated_at TEXT);
        CREATE TABLE worker_events (
            id INTEGER PRIMARY KEY, event_type TEXT, status TEXT, created_at TEXT
        );
        """
    )
    con.commit()
    con.close()
    return db


def _heartbeat(db: Path, *, sql_offset: str = "now") -> None:
    con = sqlite3.connect(db)
    con.execute(
        f"INSERT INTO live_runtime_heartbeat (updated_at) VALUES (datetime('{sql_offset}'))"
    )
    con.commit()
    con.close()


def _enqueue_live(db: Path, task_id: str, *, age: str = "now") -> None:
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO autonomous_tasks (task_id, task_type, status, created_at, updated_at)"
        f" VALUES (?, 'pulse_check', 'pending', datetime('{age}'), datetime('{age}'))",
        (task_id,),
    )
    con.commit()
    con.close()


def test_no_eligible_work_is_idle_not_healthy(tmp_path: Path) -> None:
    """Sin trabajo elegible y con el latido al día: `idle`.

    "Sano y sin nada que hacer" no es lo mismo que "sano y trabajando". Para
    quien vigila 24/7, confundirlos es perder la única señal que distingue una
    noche tranquila de un organismo parado.
    """
    db = _db(tmp_path)
    _heartbeat(db)

    health = ServiceHealth(db).inspect(process_running=True, ollama_probe=_OLLAMA_OK)

    assert health.state == "idle", f"estado={health.state} razones={health.reasons}"


def test_eligible_work_that_never_advances_is_stalled(tmp_path: Path) -> None:
    """Trabajo elegible y viejo, sin nada completándose: `stalled`.

    Antes esto no se detectaba: la señal miraba `worker_tasks`, que lleva
    congelada desde el 2026-07-29, así que la cola siempre parecía vacía.
    """
    db = _db(tmp_path)
    _heartbeat(db)
    _enqueue_live(db, "t-vieja", age="now,-2 hours")

    health = ServiceHealth(db).inspect(process_running=True, ollama_probe=_OLLAMA_OK)

    assert health.state == "stalled", f"estado={health.state} razones={health.reasons}"
    assert "queue_not_progressing" in health.reasons


def test_recent_completions_keep_it_healthy(tmp_path: Path) -> None:
    """Con trabajo pendiente pero cerrando tareas, el organismo está sano."""
    db = _db(tmp_path)
    _heartbeat(db)
    _enqueue_live(db, "t-nueva", age="now,-2 hours")
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO autonomous_tasks (task_id, task_type, status, created_at, updated_at)"
        " VALUES ('t-hecha','pulse_check','completed',datetime('now'),datetime('now'))"
    )
    con.commit()
    con.close()

    health = ServiceHealth(db).inspect(process_running=True, ollama_probe=_OLLAMA_OK)

    assert health.state == "healthy", f"estado={health.state} razones={health.reasons}"


def test_progress_metrics_come_from_the_living_queue(tmp_path: Path) -> None:
    """Las métricas de progreso no pueden salir de la tabla retirada."""
    db = _db(tmp_path)
    _heartbeat(db)
    _enqueue_live(db, "t-1")
    con = sqlite3.connect(db)
    # Ruido en la tabla muerta: no debe aparecer en las metricas de progreso.
    con.execute(
        "INSERT INTO worker_tasks (task_type, status, created_at)"
        " VALUES ('pulse_check','completed',datetime('now','-3 days'))"
    )
    con.commit()
    con.close()

    metrics = (
        ServiceHealth(db).inspect(process_running=True, ollama_probe=_OLLAMA_OK).metrics
    )

    assert metrics["queue"].get("pending") == 1
    assert "completed" not in metrics["queue"], (
        f"la cola de progreso arrastra filas de la tabla retirada: {metrics['queue']}"
    )
    assert metrics.get("legacy_queue", {}).get("completed") == 1

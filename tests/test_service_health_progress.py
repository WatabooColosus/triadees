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

import pytest

from triade.runtime.service_health import ServiceHealth

_OLLAMA_OK = {"ollama_ok": True}


@pytest.fixture(autouse=True)
def healthy_ram_for_queue_progress_contract(permitted_runtime_ram):
    pass


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
            id INTEGER PRIMARY KEY, event_type TEXT, status TEXT, created_at TEXT, task_type TEXT
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


def test_iso_errors_outside_the_window_do_not_degrade_health(tmp_path: Path) -> None:
    """ISO-8601 con ``T`` no se compara lexicalmente con ``datetime()``.

    SQLite devuelve ``YYYY-MM-DD HH:MM`` para ``datetime('now')``. Los eventos
    del runtime usan ``YYYY-MM-DDTHH:MM+00:00``; comparar ambos como texto hacía
    que cualquier error del mismo día pareciera reciente hasta medianoche.
    """
    db = _db(tmp_path)
    _heartbeat(db)
    con = sqlite3.connect(db)
    for index in range(5):
        con.execute(
            "INSERT INTO worker_events (id,event_type,status,created_at) "
            "VALUES (?, 'old_error', 'error', datetime('now','-1 hour') || 'Z')",
            (index + 1,),
        )
    con.commit()
    con.close()

    health = ServiceHealth(db).inspect(process_running=True, ollama_probe=_OLLAMA_OK)

    assert health.metrics["recent_repeated_errors"] == 0
    assert "repeated_worker_errors" not in health.reasons


def test_backup_fault_is_distinct_from_worker_crashes(
    tmp_path: Path, monkeypatch
) -> None:
    """Repeated planner warnings are not six independent failed worker runs."""
    from triade.memory.encrypted_backup import EncryptedBackup

    db = _db(tmp_path)
    _heartbeat(db)
    monkeypatch.setattr(
        EncryptedBackup,
        "key_status",
        classmethod(lambda cls: {"configured": False, "source": "none"}),
    )
    with sqlite3.connect(db) as conn:
        for event_id in range(1, 7):
            conn.execute(
                """INSERT INTO worker_events
                   (id,event_type,status,created_at,task_type)
                   VALUES (?, 'internal_error','error',datetime('now'),
                   'mission_planner.backup_key_missing')""",
                (event_id,),
            )
    health = ServiceHealth(db).inspect(process_running=True, ollama_probe=_OLLAMA_OK)
    assert health.state == "degraded"
    assert "encrypted_backup_key_missing" in health.reasons
    assert "repeated_worker_errors" not in health.reasons
    assert health.metrics["recent_backup_key_errors"] == 6
    assert health.metrics["recent_repeated_errors"] == 0


def test_missing_backup_key_is_detected_without_worker_error_log(
    tmp_path: Path, monkeypatch
) -> None:
    """No logs is not evidence of working encrypted backups."""
    from triade.memory.encrypted_backup import EncryptedBackup

    db = _db(tmp_path)
    _heartbeat(db)
    monkeypatch.setenv("TRIADE_REQUIRE_ENCRYPTED_BACKUP", "1")
    monkeypatch.setattr(
        EncryptedBackup,
        "key_status",
        classmethod(lambda cls: {"configured": False, "source": "none"}),
    )
    health = ServiceHealth(db).inspect(process_running=True, ollama_probe=_OLLAMA_OK)
    assert health.state == "degraded"
    assert "encrypted_backup_key_missing" in health.reasons
    assert health.metrics["encrypted_backup"]["usable"] is False


def test_scheduler_completions_do_not_inflate_applied_learning(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _heartbeat(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE neuron_education_applications (id INTEGER PRIMARY KEY)"
        )
        conn.execute("CREATE TABLE neuron_education_sessions (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE trainable_adapters (id INTEGER PRIMARY KEY)")
        conn.execute(
            "INSERT INTO autonomous_tasks "
            "(task_id,task_type,status,created_at,updated_at) "
            "VALUES ('educated-run', 'neuron_education_cycle', 'completed', "
            "datetime('now'), datetime('now'))"
        )
    health = ServiceHealth(db).inspect(process_running=True, ollama_probe=_OLLAMA_OK)
    evidence = health.metrics["measured_outcomes"]
    assert evidence["education_tasks_completed"] == 1
    assert evidence["education_applications"] == 0
    assert evidence["trainable_adapters"] == 0


def test_backup_fault_remains_visible_after_log_throttling(
    tmp_path: Path, monkeypatch
) -> None:
    """Backup fault cannot disappear from health 15 minutes after its only log."""
    from triade.memory.encrypted_backup import EncryptedBackup

    db = _db(tmp_path)
    _heartbeat(db)
    monkeypatch.setattr(
        EncryptedBackup,
        "key_status",
        classmethod(lambda cls: {"configured": False, "source": "none"}),
    )
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO worker_events
               (id,event_type,status,created_at,task_type)
               VALUES (1,'internal_error','error',datetime('now','-30 minutes'),
               'mission_planner.backup_key_missing')"""
        )
    health = ServiceHealth(db).inspect(process_running=True, ollama_probe=_OLLAMA_OK)
    assert health.state == "degraded"
    assert "encrypted_backup_key_missing" in health.reasons
    assert "repeated_worker_errors" not in health.reasons
    assert health.metrics["recent_repeated_errors"] == 0
    assert health.metrics["backup_key_fault_observed"] is True


def test_learning_health_requires_real_neuron_activity_not_only_completed_tasks(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    _heartbeat(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE neuron_education_sessions (state TEXT)"
        )
        conn.execute(
            "CREATE TABLE neuron_activity (id INTEGER PRIMARY KEY)"
        )
        conn.execute(
            "CREATE TABLE verification_reports (id INTEGER PRIMARY KEY)"
        )
        conn.execute(
            "INSERT INTO neuron_education_sessions VALUES('lesson_prepared')"
        )
        conn.execute(
            "INSERT INTO verification_reports VALUES(1)"
        )
        conn.execute(
            "INSERT INTO autonomous_tasks "
            "(task_id,task_type,status,created_at,updated_at) "
            "VALUES ('education-run','neuron_education_cycle','completed',"
            "datetime('now'),datetime('now'))"
        )
    health = ServiceHealth(db).inspect(process_running=True, ollama_probe=_OLLAMA_OK)
    metrics = health.metrics["measured_outcomes"]
    assert metrics["education_tasks_completed"] == 1
    assert metrics["neuron_activations_recorded"] == 0
    assert metrics["verification_reports"] == 1
    assert "education_neuron_activity_missing" in health.reasons
    assert health.state == "degraded"

    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO neuron_activity VALUES(1)")
    recovered = ServiceHealth(db).inspect(
        process_running=True, ollama_probe=_OLLAMA_OK
    )
    assert "education_neuron_activity_missing" not in recovered.reasons

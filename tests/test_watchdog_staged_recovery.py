"""El watchdog escala: primero reconcilia, y sólo después reinicia.

Dos defectos del contrato anterior:

1. `RuntimeRecovery.recover()` **para los workers antes de intentar nada**. Un
   lease vencido —lo más común y lo más barato de arreglar— tumbaba todo el
   loop. Eso es reiniciar el organismo entero por una tarea, que es justo lo
   que este runtime existe para no hacer.

2. El presupuesto de recuperación (`_recoveries`) sólo se reiniciaba al ver
   `healthy`. Con el estado `idle` recién añadido, un organismo que se recupera
   y se queda sin trabajo conserva el contador; a la tercera vez agota el
   presupuesto y deja de recuperarse **estando sano**. `idle` es un estado sano:
   significa "no hay nada que hacer", no "sigo roto".
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from triade.runtime.service_health import ServiceHealth
from triade.runtime.task_leases import AutonomousTaskStore
from triade.runtime.watchdog import RuntimeWatchdog

_PROBE = {
    "disk": {"free_gb": 10},
    "memory": {"available_gb": 10},
    "thermal": {"thermal_status": "ok"},
}


def _db(path):
    AutonomousTaskStore(path)
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE worker_tasks(id INTEGER PRIMARY KEY,status TEXT,created_at TEXT);
        CREATE TABLE worker_runs(id INTEGER PRIMARY KEY,status TEXT,started_at TEXT,finished_at TEXT);
        CREATE TABLE worker_state(key TEXT,updated_at TEXT,value_json TEXT);
        CREATE TABLE worker_events(id INTEGER PRIMARY KEY,status TEXT,created_at TEXT);
        """)
        conn.execute(
            "INSERT INTO worker_state VALUES('workers',?, '{}')",
            (datetime.now(UTC).isoformat(),),
        )


def test_idle_resets_the_recovery_budget(tmp_path, monkeypatch):
    """`idle` es sano. No puede consumir el presupuesto de recuperación.

    Si no se reinicia el contador, un organismo que se recupera y se queda sin
    trabajo agota el presupuesto a la tercera y deja de recuperarse estando
    perfectamente.
    """
    monkeypatch.setattr(
        "triade.runtime.service_health.build_resource_probe", lambda: _PROBE
    )
    path = tmp_path / "health.db"
    _db(path)
    dog = RuntimeWatchdog(path, max_recoveries=3)
    dog._recoveries = 2

    out = dog.tick(process_running=True, ollama_probe={"ok": True})

    assert out["health"]["state"] == "idle", out["health"]["state"]
    assert out["recovery_attempts"] == 0, (
        "el estado idle no devolvió el presupuesto de recuperación"
    )


def test_expired_leases_are_reconciled_without_restarting_workers(
    tmp_path, monkeypatch
):
    """Un lease vencido se arregla reconciliando, no reiniciando.

    El organismo está atascado por una sola causa barata. Parar y arrancar todo
    el loop de workers para eso es desproporcionado: mata tareas sanas que iban
    bien para rescatar una que no.
    """
    monkeypatch.setattr(
        "triade.runtime.service_health.build_resource_probe", lambda: _PROBE
    )
    path = tmp_path / "health.db"
    _db(path)

    # Una tarea vieja, elegible y sin cerrar: el organismo parece atascado.
    vieja = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    with sqlite3.connect(path) as conn:
        conn.execute(
            """INSERT INTO autonomous_tasks
               (task_id,task_type,idempotency_key,status,priority,created_at,updated_at,
                max_attempts,payload_json,payload_hash,worker_id,lease_expires_at)
               VALUES('t-vieja','pulse_check','k1','leased',50,?,?,3,'{}','h','w',?)""",
            (vieja, vieja, vieja),
        )

    assert (
        ServiceHealth(path)
        .inspect(process_running=True, ollama_probe={"ok": True})
        .state
        == "stalled"
    )

    parados: list[str] = []
    arrancados: list[str] = []
    dog = RuntimeWatchdog(path, max_recoveries=3, recovery_cooldown_seconds=0)

    out = dog.tick(
        process_running=True,
        ollama_probe={"ok": True},
        stop_workers=lambda: parados.append("stop"),
        start_workers=lambda: arrancados.append("start"),
        verify_heartbeat=lambda: True,
    )

    recovery = out["recovery"] or {}
    assert recovery.get("stage") == "reconciled", (
        f"no se intentó la reconciliación barata primero: {recovery}"
    )
    assert parados == [], "se pararon los workers por un lease vencido"
    assert arrancados == [], "se rearrancaron los workers sin hacer falta"


def test_restart_still_happens_when_reconciling_is_not_enough(tmp_path, monkeypatch):
    """Si reconciliar no basta, se escala. El escalón sigue existiendo.

    El arreglo no puede convertirse en "nunca reiniciar": eso cambiaría un
    exceso por una omisión.
    """
    monkeypatch.setattr(
        "triade.runtime.service_health.build_resource_probe", lambda: _PROBE
    )
    path = tmp_path / "health.db"
    _db(path)
    # Latido antiguo: reconciliar leases no lo arregla.
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE worker_state SET updated_at=?",
            ((datetime.now(UTC) - timedelta(hours=2)).isoformat(),),
        )

    parados: list[str] = []
    arrancados: list[str] = []
    dog = RuntimeWatchdog(path, max_recoveries=3, recovery_cooldown_seconds=0)

    dog.tick(
        process_running=True,
        ollama_probe={"ok": True},
        stop_workers=lambda: parados.append("stop"),
        start_workers=lambda: arrancados.append("start"),
        verify_heartbeat=lambda: True,
    )

    assert parados == ["stop"], "no se escaló a reinicio cuando hacía falta"
    assert arrancados == ["start"]

"""El sensor de leases debe mirar la cola que existe, no la retirada.

Auditoría 2026-08-02. Encontrado en runtime real: dos `neuron_education_cycle`
llevaban 12 y 6 minutos en `running` con el lease vencido y nadie las recuperaba,
mientras el resto de la cola avanzaba y el sistema se declaraba sano.

La cadena rota, entera:

    HealthSensors._check_leases()   -> consulta `worker_tasks.status='claimed'`
    NeedsQueue.detect()             -> `if not leases["ok"]` nunca se cumple
    MetabolicCoordinator            -> la necesidad `lease_supervision` no nace
    AutonomousTaskStore.recover_expired()  -> nunca se llama en producción

`worker_tasks` es la cola legacy: cero filas `claimed` en toda su historia y
ninguna escritura desde 2026-07-29. El runtime always-on usa `autonomous_tasks`
con estados `leased`/`running`. El sensor vigilaba una tabla muerta, así que
`recover_expired()` —que está bien escrita y cubre ambos estados— no tenía quien
la activara.

Estas pruebas fijan el contrato por el que se detecta un lease vencido: sobre la
cola viva, y con el estado que el runtime escribe de verdad.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from triade.metabolism.health import HealthSensors
from triade.metabolism.needs import NeedsQueue
from triade.runtime.task_leases import AutonomousTaskStore


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _store_with_expired_lease(db_path: Path) -> str:
    """Deja una tarea `running` con el lease vencido, como la vista en runtime."""
    store = AutonomousTaskStore(db_path)
    task = store.enqueue("pulse_check", {}, idempotency_key="lease-sensor-probe")
    task_id = str(task["task_id"])
    expired = _iso(datetime.now(UTC) - timedelta(minutes=10))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """UPDATE autonomous_tasks
            SET status='running', worker_id='worker-muerto',
                lease_acquired_at=?, lease_expires_at=?
            WHERE task_id=?""",
            (_iso(datetime.now(UTC) - timedelta(minutes=11)), expired, task_id),
        )
        conn.commit()
    return task_id


class TestLeaseSensorSeesLiveQueue:
    def test_expired_lease_in_live_queue_is_not_ok(self, tmp_path: Path) -> None:
        """Un lease vencido en `autonomous_tasks` no puede reportarse sano."""
        db = tmp_path / "triade.db"
        _store_with_expired_lease(db)

        leases = HealthSensors(db).inspect()["leases"]

        assert leases["ok"] is False, (
            "el sensor declaró sano un lease vencido: mira la tabla equivocada"
        )
        assert leases["stale_leases"] == 1

    def test_legacy_table_does_not_mask_live_staleness(self, tmp_path: Path) -> None:
        """`worker_tasks` viva y sin `claimed` no puede tapar la cola real.

        Es la forma exacta del fallo en producción: la tabla legacy existe, está
        limpia, y por eso el sensor daba `ok`.
        """
        db = tmp_path / "triade.db"
        _store_with_expired_lease(db)
        with sqlite3.connect(db) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS worker_tasks(
                id INTEGER PRIMARY KEY, task_type TEXT, status TEXT,
                started_at TEXT, created_at TEXT)"""
            )
            conn.execute(
                "INSERT INTO worker_tasks(task_type,status,created_at) "
                "VALUES('pulse_check','completed',datetime('now'))"
            )
            conn.commit()

        assert HealthSensors(db).inspect()["leases"]["ok"] is False

    def test_healthy_lease_is_still_ok(self, tmp_path: Path) -> None:
        """Un lease vigente no puede disparar recuperación: no hay falso positivo."""
        db = tmp_path / "triade.db"
        store = AutonomousTaskStore(db)
        task = store.enqueue("pulse_check", {}, idempotency_key="vigente")
        with sqlite3.connect(db) as conn:
            conn.execute(
                """UPDATE autonomous_tasks
                SET status='running', worker_id='worker-vivo',
                    lease_acquired_at=?, lease_expires_at=?
                WHERE task_id=?""",
                (
                    _iso(datetime.now(UTC)),
                    _iso(datetime.now(UTC) + timedelta(minutes=5)),
                    str(task["task_id"]),
                ),
            )
            conn.commit()

        leases = HealthSensors(db).inspect()["leases"]
        assert leases["ok"] is True
        assert leases["stale_leases"] == 0

    def test_empty_queue_is_ok(self, tmp_path: Path) -> None:
        """Sin cola no hay staleness: arrancar en vacío no es degradación."""
        db = tmp_path / "triade.db"
        AutonomousTaskStore(db)
        assert HealthSensors(db).inspect()["leases"]["ok"] is True


class TestStaleLeaseProducesSupervisionNeed:
    """El eslabón que faltaba: del sensor a la necesidad que recupera."""

    def test_stale_lease_creates_lease_supervision_need(self, tmp_path: Path) -> None:
        db = tmp_path / "triade.db"
        _store_with_expired_lease(db)
        sensors = HealthSensors(db).inspect()

        needs = NeedsQueue(db).detect(sensors, cycle_id=1)

        kinds = [need.kind for need in needs]
        assert "lease_supervision" in kinds, (
            "un lease vencido no generó la necesidad que lo recupera; "
            f"necesidades emitidas: {kinds}"
        )

    def test_healthy_runtime_does_not_create_the_need(self, tmp_path: Path) -> None:
        """No se recupera lo que no está roto."""
        db = tmp_path / "triade.db"
        AutonomousTaskStore(db)
        sensors = HealthSensors(db).inspect()

        needs = NeedsQueue(db).detect(sensors, cycle_id=1)

        assert "lease_supervision" not in [need.kind for need in needs]

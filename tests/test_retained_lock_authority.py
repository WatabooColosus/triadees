"""Un PID vivo no basta para conservar la autoridad del runtime.

`worker_loop.run()` conserva el fichero de lock a propósito cuando el run cierra
con tareas todavía vivas (`_retain_lock_for_active_tasks`). La razón es buena:
soltarlo dejaría entrar a otro worker sobre la misma base mientras las tareas
siguen escribiendo.

El defecto está en cómo se recupera. `recover_interrupted_runtime` devuelve
`live_owner` **siempre que el PID esté vivo**, y en el runtime siempre-activo ese
PID es el de `uvicorn`, que vive toda la sesión. Así que el lock retenido no se
recupera nunca mientras la app siga en pie: un run que terminó hace horas, con
sus tareas hace mucho acabadas, mantiene bloqueado el sistema entero.

Es literalmente "una tarea puede detener todo el sistema".

El contrato correcto: la autoridad pertenece a un RUN, no a un proceso. Un lock
retenido sigue siendo válido mientras su run tenga trabajo en vuelo de verdad, y
deja de serlo cuando la última tarea termina — lo compruebe quien lo compruebe,
y sin importar que el proceso siga vivo.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from triade.runtime.process_lock import RuntimeProcessLock
from triade.runtime.task_leases import AutonomousTaskStore
from triade.workers.contracts import WorkerRunConfig
from triade.workers.state_store import WorkerStateStore


def _lock_owned_by_this_process(path: Path, run_ref: str | None = None) -> None:
    payload = json.loads(RuntimeProcessLock.payload().decode("utf-8"))
    if run_ref is not None:
        payload["run_ref"] = run_ref
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_retained_lock_is_recovered_once_its_run_has_no_work_left(tmp_path):
    """El caso que paraba el organismo.

    Run cerrado con tareas vivas, tareas ya terminadas, proceso todavía vivo.
    La autoridad tiene que poder recuperarse.
    """
    db = tmp_path / "triade.db"
    lock = tmp_path / "worker.lock"
    store = WorkerStateStore(db)
    store.create_worker_run("run-huerfano", WorkerRunConfig(), tmp_path / "artifacts")
    store.finish_worker_run("run-huerfano", "completed_with_active_tasks", {})
    _lock_owned_by_this_process(lock, run_ref="run-huerfano")

    result = store.recover_interrupted_runtime(lock)

    assert result["status"] != "live_owner", (
        "un run terminado sin trabajo en vuelo retuvo la autoridad porque el "
        "proceso sigue vivo"
    )
    assert not lock.exists()


def test_retained_lock_survives_while_its_run_still_has_work_in_flight(tmp_path):
    """Lo contrario también tiene que ser cierto, o el arreglo es peor.

    Mientras quede una tarea en vuelo del run dueño, nadie puede quitarle la
    autoridad: soltarla dejaría entrar a otro worker sobre la misma base.
    """
    db = tmp_path / "triade.db"
    lock = tmp_path / "worker.lock"
    store = WorkerStateStore(db)
    store.create_worker_run("run-ocupado", WorkerRunConfig(), tmp_path / "artifacts")
    store.finish_worker_run("run-ocupado", "completed_with_active_tasks", {})

    leases = AutonomousTaskStore(db)
    task_id = leases.enqueue("pulse_check", {"n": 1}, idempotency_key="k1")["task_id"]
    claimed = leases.claim_task(task_id, worker_id="run-ocupado", lease_seconds=600)
    assert claimed is not None, "la tarea no quedó arrendada por el run dueño"

    _lock_owned_by_this_process(lock, run_ref="run-ocupado")

    result = store.recover_interrupted_runtime(lock)

    assert result["status"] == "live_owner"
    assert lock.exists()


def test_expired_lease_does_not_keep_the_authority_alive(tmp_path):
    """Un lease caducado no es trabajo en vuelo.

    Si bastara la fila en la tabla, un worker muerto a media tarea dejaría la
    autoridad retenida para siempre — el mismo agujero por otra puerta.
    """
    db = tmp_path / "triade.db"
    lock = tmp_path / "worker.lock"
    store = WorkerStateStore(db)
    store.create_worker_run("run-caducado", WorkerRunConfig(), tmp_path / "artifacts")
    store.finish_worker_run("run-caducado", "completed_with_active_tasks", {})

    leases = AutonomousTaskStore(db)
    task_id = leases.enqueue("pulse_check", {"n": 2}, idempotency_key="k2")["task_id"]
    assert leases.claim_task(task_id, worker_id="run-caducado", lease_seconds=-600)

    _lock_owned_by_this_process(lock, run_ref="run-caducado")

    result = store.recover_interrupted_runtime(lock)

    assert result["status"] != "live_owner"
    assert not lock.exists()


def test_a_run_still_marked_running_keeps_its_authority(tmp_path):
    """El caso normal: el worker está trabajando de verdad. No se le toca."""
    db = tmp_path / "triade.db"
    lock = tmp_path / "worker.lock"
    store = WorkerStateStore(db)
    store.create_worker_run("run-vivo", WorkerRunConfig(), tmp_path / "artifacts")
    _lock_owned_by_this_process(lock, run_ref="run-vivo")

    result = store.recover_interrupted_runtime(lock)

    assert result["status"] == "live_owner"
    assert lock.exists()


def test_legacy_lock_without_run_keeps_the_old_contract(tmp_path):
    """Sin `run_ref` no hay nada que comprobar: se conserva lo de siempre.

    Un lock escrito por una versión anterior no dice a qué run pertenece. Ante
    la duda, se respeta al proceso vivo — que es la dirección conservadora.
    """
    db = tmp_path / "triade.db"
    lock = tmp_path / "worker.lock"
    _lock_owned_by_this_process(lock)

    result = WorkerStateStore(db).recover_interrupted_runtime(lock)

    assert result["status"] == "live_owner"
    assert lock.exists()


def test_authority_is_not_stolen_from_another_live_process(tmp_path):
    """Fencing: un run desconocido con PID vivo no se toca.

    Si el lock nombra un run que esta base no conoce, no hay forma de demostrar
    que su trabajo terminó. No demostrarlo es razón suficiente para no tocarlo.
    """
    db = tmp_path / "triade.db"
    lock = tmp_path / "worker.lock"
    _lock_owned_by_this_process(lock, run_ref="run-de-otra-base")

    result = WorkerStateStore(db).recover_interrupted_runtime(lock)

    assert result["status"] == "live_owner"
    assert lock.exists()


def test_dead_process_is_recovered_regardless_of_its_run(tmp_path):
    """Lo que ya funcionaba sigue funcionando: PID muerto, lock recuperable."""
    db = tmp_path / "triade.db"
    lock = tmp_path / "worker.lock"
    payload = json.loads(RuntimeProcessLock.payload().decode("utf-8"))
    payload["pid"] = 99999999
    payload["run_ref"] = "run-de-un-muerto"
    lock.write_text(json.dumps(payload), encoding="utf-8")

    result = WorkerStateStore(db).recover_interrupted_runtime(lock)

    assert result["status"] == "recovered"
    assert not lock.exists()
    assert os.getpid() != 99999999

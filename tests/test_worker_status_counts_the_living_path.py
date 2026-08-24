"""`task_counts` tiene que contar las tareas que de verdad se ejecutan.

Salía de `worker_tasks`, una tabla que dejó de escribirse el 2026-07-29. Medido
sobre la base de producción el 2026-08-01:

    worker_tasks.MAX(created_at)      = 2026-07-29T07:26:24   (0 filas en 24h)
    autonomous_tasks.MAX(updated_at)  = 2026-08-01T05:22:24   (1367 filas en 24h)

Es decir: el panel decía "1802 completadas" y llevaba **tres días congelado**
mientras el organismo cerraba ~520 tareas cada diez minutos. Quien mirara la
Cabina Viva concluía que Tríade estaba parada.

No es un número mal calculado. Es un número que dejó de existir cuando la
ejecución migró a `autonomous_tasks` con leases, y nadie movió el contador
detrás. Lo consumen `App.tsx` (el panel) y `observability_view.pending_tasks`,
así que la mentira llegaba hasta la pantalla.

El campo que se llama "tareas" cuenta las tareas. Lo heredado conserva su
número, pero con un nombre que dice lo que es.
"""

from __future__ import annotations

from pathlib import Path

from triade.runtime.legacy_compatibility import LegacyCompatibilityController
from triade.runtime.task_leases import AutonomousTaskStore
from triade.workers.state_store import WorkerStateStore


def test_task_counts_reflects_the_path_that_actually_executes(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    store = WorkerStateStore(db)
    leases = AutonomousTaskStore(db)

    leases.enqueue("pulse_check", {"n": 1}, idempotency_key="viva-1")
    hecha = leases.enqueue("pulse_check", {"n": 2}, idempotency_key="viva-2")
    claimed = leases.claim_task(hecha["task_id"], worker_id="run-x", lease_seconds=60)
    assert claimed is not None
    # `complete()` exige un artefacto que exista de verdad: no se declara hecho
    # lo que no dejó rastro.
    artefacto = tmp_path / "resultado.json"
    artefacto.write_text("{}", encoding="utf-8")
    assert leases.complete(
        hecha["task_id"], "run-x", int(claimed["lease_generation"]), str(artefacto)
    )

    counts = store.status()["task_counts"]

    assert counts.get("completed") == 1, (
        f"el contador no ve el trabajo real del organismo: {counts}"
    )
    assert counts.get("pending") == 1, (
        f"el contador no ve la cola real del organismo: {counts}"
    )


def test_the_legacy_table_keeps_its_own_named_counter(tmp_path: Path) -> None:
    """Lo heredado no se borra: se etiqueta.

    Hay 1802 filas reales en `worker_tasks` de cuando ese era el camino. Siguen
    siendo historia cierta. Lo que no puede es seguir llamándose "las tareas".

    Y no es que la tabla se abandonara por descuido: `019_legacy_retirement.sql`
    instala un trigger que **aborta** cualquier escritura
    (`legacy_worker_task_writes_disabled`). Estaba retirada a propósito, y el
    panel seguía contándola. Para escribir en ella hay que pedir compatibilidad
    heredada explícitamente, que es lo que hace esta prueba.
    """
    db = tmp_path / "triade.db"
    store = WorkerStateStore(db)
    LegacyCompatibilityController(db).set_compatibility(
        enabled=True, actor="test", reason="fijar el contador heredado"
    )
    tarea = store.enqueue_task("pulse_check", {})
    claimed = store.claim_next_task()
    assert claimed is not None
    store.finish_task(claimed.id or 0, "completed", {"ok": True}, "approved")

    estado = store.status()
    assert estado["legacy_task_counts"].get("completed") == 1
    assert tarea.id is not None


def test_pending_tasks_on_the_dashboard_is_not_frozen(tmp_path: Path) -> None:
    """`observability_view.pending_tasks` sale de `task_counts`.

    Si el contador miente, la pantalla miente. Se fija aquí para que no se
    vuelva a desconectar en silencio.
    """
    db = tmp_path / "triade.db"
    store = WorkerStateStore(db)
    leases = AutonomousTaskStore(db)
    for i in range(3):
        leases.enqueue("pulse_check", {"n": i}, idempotency_key=f"pend-{i}")

    assert store.status()["task_counts"].get("pending") == 3


def test_worker_status_publica_el_switch_legacy_sin_cambiarlo(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    status = WorkerStateStore(db).status()["queue_compatibility"]

    assert status["mode"] == "v2_canonical"
    assert status["compatibility_events"] == 0

"""Una tarea no puede quedarse en `completion_uncertain` para siempre.

Hallazgo de la auditoría en vivo (2026-07-31): 12 tareas llevaban hasta 20 horas
en `completion_uncertain`, la más antigua desde el día anterior.

El camino era:

1. El worker muere con una tarea en `running`.
2. `recover_interrupted_runtime()` ve el lease expirado y **sin artefacto**, así
   que la marca `completion_uncertain` con razón `recovery_no_artifact`.
3. `reconcile_uncertain_completions()` busca su artefacto, no lo encuentra, y
   hace `failed += 1` — **cuenta, pero no transiciona**.

Nadie la saca nunca. No es un estado terminal ni uno activo: es limbo. Y como
las herramientas de monitorización cuentan `completion_uncertain` entre las
tareas vivas, el sistema **afirma actividad que no existe**, que es justo lo que
este runtime no puede permitirse.

La corrección no es reintentar a ciegas —sin artefacto no sabemos si el efecto
llegó a aplicarse, y repetir un `goal_safe_command` podría aplicarlo dos veces—
sino cerrarla como `dead_letter` diciendo exactamente por qué.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.runtime.task_leases import AutonomousTaskStore


def _uncertain_task(store: AutonomousTaskStore, *, with_artifact: Path | None) -> str:
    """Deja una tarea en `completion_uncertain`, como haría la recuperación."""
    task = store.enqueue("pulse_check", {}, idempotency_key=f"unc-{id(store)}")
    task_id = str(task["task_id"])
    leased = store.claim_task(task_id, "worker-muerto", lease_seconds=60)
    assert leased is not None
    generation = int(leased["lease_generation"])
    assert store.start(task_id, "worker-muerto", generation)
    ref = str(with_artifact) if with_artifact else ""
    if ref:
        assert store.prepare_completion(task_id, "worker-muerto", generation, ref)
    else:
        # Reproduce literalmente lo que hace la recuperación: sin `result_ref`.
        with sqlite3.connect(store.db_path) as conn:
            conn.execute(
                """UPDATE autonomous_tasks
                SET status='completion_uncertain', result_ref=NULL
                WHERE task_id=?""",
                (task_id,),
            )
    return task_id


def _status(store: AutonomousTaskStore, task_id: str) -> str:
    return str((store.get(task_id) or {}).get("status") or "")


def test_uncertain_with_artifact_completes(tmp_path: Path) -> None:
    """El camino bueno no debe cambiar: si el artefacto está, se completa."""
    store = AutonomousTaskStore(tmp_path / "triade.db")
    artifact = tmp_path / "result.json"
    artifact.write_text("{}", encoding="utf-8")
    task_id = _uncertain_task(store, with_artifact=artifact)

    report = store.reconcile_uncertain_completions()

    assert report["completed"] == 1
    assert _status(store, task_id) == "completed"


def test_uncertain_without_artifact_does_not_stay_forever(tmp_path: Path) -> None:
    """El defecto: sin artefacto se quedaba en limbo indefinidamente."""
    store = AutonomousTaskStore(tmp_path / "triade.db")
    task_id = _uncertain_task(store, with_artifact=None)
    assert _status(store, task_id) == "completion_uncertain"

    store.reconcile_uncertain_completions()

    assert _status(store, task_id) != "completion_uncertain", (
        "la tarea sigue en limbo: ni terminó ni volvió a la cola"
    )


def test_uncertain_without_artifact_becomes_dead_letter(tmp_path: Path) -> None:
    """Se cierra como `dead_letter`, no se reintenta.

    Sin artefacto no sabemos si el efecto llegó a aplicarse. Reintentar un
    `goal_safe_command` a ciegas podría aplicarlo dos veces, así que se cierra
    diciendo por qué y se deja la decisión a un humano.
    """
    store = AutonomousTaskStore(tmp_path / "triade.db")
    task_id = _uncertain_task(store, with_artifact=None)

    report = store.reconcile_uncertain_completions()

    assert report["still_uncertain"] == 0
    assert report.get("dead_lettered") == 1
    assert _status(store, task_id) == "dead_letter"


def test_the_reason_is_recorded_so_it_can_be_audited(tmp_path: Path) -> None:
    """Cerrar sin decir por qué solo cambia un limbo por otro."""
    store = AutonomousTaskStore(tmp_path / "triade.db")
    task_id = _uncertain_task(store, with_artifact=None)
    store.reconcile_uncertain_completions()

    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = [
            dict(row)
            for row in conn.execute(
                """SELECT from_status, to_status, reason
                FROM autonomous_task_transitions WHERE task_id=?""",
                (task_id,),
            )
        ]
    closing = [r for r in rows if r["to_status"] == "dead_letter"]
    assert closing, "no se registró la transición de cierre"
    assert "artifact" in str(closing[-1]["reason"])
    assert closing[-1]["from_status"] == "completion_uncertain"


def test_reconciling_twice_is_idempotent(tmp_path: Path) -> None:
    store = AutonomousTaskStore(tmp_path / "triade.db")
    _uncertain_task(store, with_artifact=None)

    first = store.reconcile_uncertain_completions()
    second = store.reconcile_uncertain_completions()

    assert first.get("dead_lettered") == 1
    assert second.get("dead_lettered") == 0
    assert second["completed"] == 0


def test_nothing_uncertain_is_a_no_op(tmp_path: Path) -> None:
    store = AutonomousTaskStore(tmp_path / "triade.db")
    report = store.reconcile_uncertain_completions()
    assert report == {"completed": 0, "still_uncertain": 0, "dead_lettered": 0}

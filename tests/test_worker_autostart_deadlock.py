"""`ensure_workers_alive` no puede bloquearse a sí misma.

Incidente real (2026-07-31): la Cabina Viva se quedaba en "Cargando cabina
viva…" indefinidamente. La causa no estaba en el frontend ni en el endpoint:
`ensure_workers_alive()` tomaba `_WORKER_LOCK` y, con los workers vivos, llamaba
dentro a `build_workers_always_on_status()`, que vuelve a pedir el mismo lock.

`threading.Lock` no es reentrante. El hilo se quedaba esperándose a sí mismo
**sin soltar el lock**, y todo el que lo necesitara se colgaba detrás: los 50
hilos del pool de FastAPI terminaron ahí, y con ellos cualquier endpoint
síncrono.

Lo peor del fallo era cuándo aparecía: solo con los workers vivos, que es
exactamente cuando alguien abre el panel para comprobar si están vivos.
"""

from __future__ import annotations

import threading
from pathlib import Path

import triade.core.worker_autostart as autostart

#: Configuración mínima que activa la rama `alive`, que es la que se colgaba.
_CONFIG = {"workers_always_on": True, "workers_autostart": True}


def _call_with_timeout(fn, seconds: float = 20.0) -> bool:
    """`True` si `fn` termina **sin excepción** a tiempo.

    La primera versión solo miraba si el hilo terminaba, y por eso daba verde
    cuando `fn` reventaba de inmediato: un `TypeError` por firma equivocada
    "terminaba a tiempo". Una prueba de deadlock que pasa porque la función ni
    siquiera se ejecutó es peor que no tenerla.
    """
    done = threading.Event()
    failure: list[BaseException] = []

    def runner() -> None:
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001 - se re-lanza abajo
            failure.append(exc)
        finally:
            done.set()

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    finished = done.wait(timeout=seconds)
    if failure:
        raise failure[0]
    return finished


def test_status_does_not_deadlock_on_its_own_lock(tmp_path: Path) -> None:
    completed = _call_with_timeout(
        lambda: autostart.build_workers_always_on_status(
            db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs"
        )
    )
    assert completed, "build_workers_always_on_status se colgó"


def test_ensure_workers_alive_returns_while_workers_are_running(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """El camino que colgaba: workers ya vivos.

    Se simula un hilo vivo para forzar la rama `alive`, sin arrancar workers de
    verdad. Antes de la correccion, esta llamada no volvia jamas.
    """
    running = threading.Event()

    def spin() -> None:
        running.wait(timeout=30)

    fake_thread = threading.Thread(target=spin, daemon=True)
    fake_thread.start()
    monkeypatch.setattr(autostart, "_WORKER_THREAD", fake_thread)

    try:
        completed = _call_with_timeout(
            lambda: autostart.ensure_workers_alive(
                _CONFIG, db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs"
            )
        )
        assert completed, "ensure_workers_alive se colgo con los workers vivos"
    finally:
        running.set()


def test_the_lock_is_free_after_the_call(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Un lock que queda tomado cuelga a todos los demas, no solo al culpable."""
    running = threading.Event()
    fake_thread = threading.Thread(target=lambda: running.wait(timeout=30), daemon=True)
    fake_thread.start()
    monkeypatch.setattr(autostart, "_WORKER_THREAD", fake_thread)

    try:
        _call_with_timeout(
            lambda: autostart.ensure_workers_alive(
                _CONFIG, db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs"
            )
        )
        acquired = autostart._WORKER_LOCK.acquire(timeout=5)
        assert acquired, "_WORKER_LOCK quedo tomado tras la llamada"
        autostart._WORKER_LOCK.release()
    finally:
        running.set()

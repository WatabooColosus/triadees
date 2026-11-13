"""El metabolismo medía sin frenar, y el watchdog vigilaba sin arrancar.

Dos órganos escritos, probados e inervados que no cumplían su función por dónde
—o si— se les llamaba:

- **F-043.** El único freno del ciclo del worker era `check_ollama_blood()`: si
  el modelo respondía, se trabajaba, con el disco al 99 % o la RAM agotada. El
  governor que sabe decidir eso existía y sólo se consultaba una vez, al
  arrancar los workers; los recursos cambian durante la sesión.
- **F-040.** El watchdog estaba declarado en `deploy/systemd/`, y systemd no
  gobierna este Studio. Nadie llamaba a `tick()`: `runtime_health_snapshots`
  llevaba 3,1 días congelada mientras el panel enseñaba sus filas viejas.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.runtime import watchdog_autostart
from triade.workers.contracts import WorkerRunConfig
from triade.workers.worker_loop import WorkerLoop


def _loop(tmp_path: Path) -> WorkerLoop:
    return WorkerLoop(
        db_path=tmp_path / "triade.db",
        runs_dir=tmp_path / "runs",
        lock_file=tmp_path / "lock",
        stop_file=tmp_path / "stop",
    )


def _config(tmp_path: Path) -> WorkerRunConfig:
    return WorkerRunConfig(
        max_iterations=1,
        sleep_seconds=0,
        once=True,
        runs_dir=str(tmp_path / "runs"),
        lock_file=str(tmp_path / "lock"),
        stop_file=str(tmp_path / "stop"),
    )


# --- El freno de recursos -----------------------------------------------------


def test_sin_recursos_el_ciclo_no_arranca(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con el disco agotado, responder Ollama no puede bastar para trabajar."""
    import triade.core.resource_governor as governor

    monkeypatch.setattr(
        governor,
        "decide_work_mode",
        lambda probe, blood, requested=None: {
            "allowed_mode": "blocked",
            "reason": "Disco libre insuficiente (0.4 GB). Operaciones bloqueadas.",
        },
    )

    result = _loop(tmp_path).run(_config(tmp_path))

    assert result["status"] == "blocked"
    assert result["reason"] == "resources_exhausted"
    assert "Disco" in result["message"]


def test_el_bloqueo_por_recursos_suelta_el_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retener el lock cambiaría una parada temporal por un bloqueo permanente.

    El lock se conserva a propósito cuando quedan tareas vivas. Aquí no ha
    empezado ninguna: si no se soltara, el worker tampoco arrancaría cuando el
    disco volviera.
    """
    import triade.core.resource_governor as governor

    monkeypatch.setattr(
        governor,
        "decide_work_mode",
        lambda probe, blood, requested=None: {
            "allowed_mode": "blocked",
            "reason": "sin RAM",
        },
    )

    _loop(tmp_path).run(_config(tmp_path))

    assert not (tmp_path / "lock").exists(), "un lock retenido aquí no se recupera solo"


def test_un_sensor_roto_no_para_el_trabajo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Frenar por no saber sería cambiar una parada de recursos por una de sensor."""
    import triade.core.resource_probe as probe_mod

    def explota() -> dict:
        raise OSError("/proc ilegible")

    monkeypatch.setattr(probe_mod, "build_resource_probe", explota)

    decision = _loop(tmp_path)._governor_decision({"status": "ok"}, "run-test")

    assert decision["allowed_mode"] == "unknown"
    assert "probe_failed" in decision["reason"]


def test_la_decision_de_recursos_queda_registrada(tmp_path: Path) -> None:
    """Una decisión que sólo se ve cuando bloquea no se puede auditar después."""
    loop = _loop(tmp_path)
    # La tabla la crea la migración 032 en la base viva; aquí se declara igual
    # para que la prueba compruebe la escritura de verdad y no se salte sola.
    with sqlite3.connect(tmp_path / "triade.db") as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS metabolic_signals (
                signal_id TEXT PRIMARY KEY, cycle_id INTEGER NOT NULL,
                stage TEXT NOT NULL, need_id TEXT, signal_status TEXT NOT NULL,
                reason TEXT, timestamp TEXT NOT NULL, budget_json TEXT DEFAULT '{}')"""
        )

    loop._governor_decision({"status": "ok", "can_reason": True}, "run-test")

    with sqlite3.connect(tmp_path / "triade.db") as conn:
        filas = conn.execute(
            "SELECT signal_status, need_id FROM metabolic_signals "
            "WHERE stage = 'worker_cycle_governor'"
        ).fetchall()

    assert filas, "el governor decidió y no dejó señal"
    assert filas[0][0], "la señal debe llevar el modo permitido"
    assert filas[0][1] == "run-test", "la señal debe poder atarse a su ciclo"


# --- El watchdog --------------------------------------------------------------


def test_el_watchdog_no_arranca_si_esta_desactivado(tmp_path: Path) -> None:
    estado = watchdog_autostart.start_watchdog_if_enabled(
        {"runtime_watchdog": False}, db_path=tmp_path / "triade.db"
    )
    assert estado["enabled"] is False
    assert estado["active"] is False
    assert estado["status"] == "disabled"


def test_el_watchdog_arranca_una_sola_vez(tmp_path: Path) -> None:
    """Dos watchdogs recuperando a la vez es lo que el presupuesto evita."""
    watchdog_autostart._THREAD = None
    primero = watchdog_autostart.start_watchdog_if_enabled(
        {"runtime_watchdog": True}, db_path=tmp_path / "triade.db"
    )
    hilo = watchdog_autostart._THREAD
    segundo = watchdog_autostart.start_watchdog_if_enabled(
        {"runtime_watchdog": True}, db_path=tmp_path / "triade.db"
    )

    assert primero["status"] == "running"
    assert segundo["status"] == "running"
    assert watchdog_autostart._THREAD is hilo, "no puede haber dos hilos vigilando"
    assert watchdog_autostart.watchdog_status()["thread_alive"] is True


def test_el_intervalo_tiene_suelo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un watchdog que se despierta cada segundo es otra fuente de carga."""
    monkeypatch.setenv("TRIADE_WATCHDOG_INTERVAL", "1")
    assert watchdog_autostart._interval() == watchdog_autostart.MIN_INTERVAL_SECONDS

    monkeypatch.setenv("TRIADE_WATCHDOG_INTERVAL", "no-es-un-numero")
    assert watchdog_autostart._interval() == watchdog_autostart.DEFAULT_INTERVAL_SECONDS


def test_el_estado_del_watchdog_es_observable() -> None:
    """Un watchdog que se cae en silencio promete una vigilancia que ya no da."""
    estado = watchdog_autostart.watchdog_status()
    for clave in ("enabled", "active", "status", "ticks", "last_tick_at", "last_error"):
        assert clave in estado, clave


def test_el_watchdog_revive_el_hilo_de_workers_caido(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Estuvieron muertos 7 minutos y nadie lo notó: nadie los miraba.

    `worker_autostart` sabe reiniciar, pero sólo cuando alguien llama a
    `ensure_workers_alive()`, y quien llamaba era un endpoint HTTP. Sin petición
    humana, un hilo caído seguía caído.
    """
    llamadas: list[str] = []
    import triade.core.worker_autostart as autostart

    monkeypatch.setattr(
        autostart, "build_workers_always_on_status", lambda: {"thread_alive": False}
    )
    monkeypatch.setattr(
        autostart, "ensure_workers_alive", lambda cfg: llamadas.append("revivido")
    )

    assert watchdog_autostart._ensure_workers_alive() is True
    assert llamadas == ["revivido"]


def test_el_watchdog_no_revive_lo_que_ya_esta_vivo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import triade.core.worker_autostart as autostart

    monkeypatch.setattr(
        autostart, "build_workers_always_on_status", lambda: {"thread_alive": True}
    )
    monkeypatch.setattr(
        autostart,
        "ensure_workers_alive",
        lambda cfg: pytest.fail("no debía tocar un hilo vivo"),
    )

    assert watchdog_autostart._ensure_workers_alive() is False


def test_el_watchdog_respeta_una_parada_pedida(monkeypatch: pytest.MonkeyPatch) -> None:
    """Revivir algo que alguien paró a propósito es desobedecer, no vigilar."""
    import triade.core.worker_autostart as autostart

    monkeypatch.setattr(
        autostart,
        "build_workers_always_on_status",
        lambda: {"thread_alive": False, "stop_requested": True},
    )
    monkeypatch.setattr(
        autostart,
        "ensure_workers_alive",
        lambda cfg: pytest.fail("una parada pedida no se revierte sola"),
    )

    assert watchdog_autostart._ensure_workers_alive() is False

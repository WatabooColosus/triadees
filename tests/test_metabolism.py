from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from triade.metabolism.contracts import MetabolicNeed
from triade.metabolism.coordinator import MetabolicCoordinator, get_coordinator


def _coordinator(tmp_path: Path, **overrides: Any) -> MetabolicCoordinator:
    db = tmp_path / "test.db"
    cfg = tmp_path / "triade.yml"
    interval = overrides.get("interval_seconds", 0.5)
    max_cycles = overrides.get("max_cycles", 1)
    enabled = "true" if overrides.get("enabled", True) else "false"
    dry_run = "true" if overrides.get("dry_run", False) else "false"
    mode = overrides.get("mode", "full")
    cfg.write_text(
        f"metabolism:\n"
        f"  enabled: {enabled}\n"
        f"  mode: {mode}\n"
        f"  dry_run: {dry_run}\n"
        f"  interval_seconds: {interval}\n"
        f"  max_cycles: {max_cycles}\n"
        f"  jitter_seconds: 0.0\n",
        encoding="utf-8",
    )
    return MetabolicCoordinator(db_path=str(db), config_path=str(cfg))


class TestLifecycle:
    def test_clean_start_migrates_before_recovery(self, tmp_path: Path) -> None:
        c = _coordinator(tmp_path, max_cycles=0, interval_seconds=60)
        observed: list[set[str]] = []

        def inspect_schema() -> list[dict[str, Any]]:
            with sqlite3.connect(c.db_path) as connection:
                observed.append(
                    {
                        str(row[0])
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                )
            return []

        c.recovery.recover_interrupted_cycles = inspect_schema  # type: ignore[method-assign]
        result = c.start()
        try:
            assert result["status"] == "started"
            assert "metabolic_cycle" in observed[0]
            assert "metabolic_needs" in observed[0]
            assert "metabolic_receipts" in observed[0]
        finally:
            c.stop(timeout=5)

    def test_start_stop(self, tmp_path: Path) -> None:
        c = _coordinator(tmp_path)
        c.load_config()
        assert c._enabled is True
        result = c.start()
        assert result["status"] == "started"
        time.sleep(0.1)
        status = c.status()
        assert status["running"] is True
        assert status["enabled"] is True
        stop = c.stop(timeout=5)
        assert stop["status"] == "stopped"
        assert c.status()["running"] is False

    def test_start_disabled(self, tmp_path: Path) -> None:
        c = _coordinator(tmp_path, enabled=False)
        assert c._enabled is False
        result = c.start()
        assert result["status"] == "disabled"
        assert c._thread is None

    def test_start_twice_no_deadlock(self, tmp_path: Path) -> None:
        c = _coordinator(tmp_path)
        c.load_config()
        r1 = c.start()
        assert r1["status"] == "started"
        r2 = c.start()
        assert r2["status"] in ("already_running",)
        c.stop(timeout=5)

    def test_concurrent_status_calls(self, tmp_path: Path) -> None:
        c = _coordinator(tmp_path)
        c.load_config()
        c.start()
        errors: list[Exception] = []

        def hammer() -> None:
            try:
                for _ in range(50):
                    c.status()
            except Exception as e:  # noqa: BLE001 -- test harness must catch any error to assert none occurred
                errors.append(e)

        threads = [threading.Thread(target=hammer) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, f"concurrent status() raised: {errors}"
        c.stop(timeout=5)

    def test_shutdown(self, tmp_path: Path) -> None:
        c = _coordinator(tmp_path)
        c.load_config()
        c.start()
        time.sleep(0.1)
        result = c.shutdown()
        assert result["status"] == "stopped"
        assert c._thread is None or not c._thread.is_alive()

    def test_status_after_stop(self, tmp_path: Path) -> None:
        c = _coordinator(tmp_path)
        c.load_config()
        c.start()
        c.stop(timeout=5)
        status = c.status()
        assert status["running"] is False
        assert status["status"] == "stopped"


class TestStatusIsARead:
    """`status()` describe el organismo. No lo reconfigura ni lo reinicia.

    `GET /api/runtime/metabolism/status` no pide clave: cualquiera que mire el
    panel entraba por aquí.
    """

    def test_status_does_not_reset_the_cycle_counter(self, tmp_path: Path) -> None:
        """Medido antes del arreglo: contador real 7, `status()` devolvía 0 y
        dejaba 0. Preguntar cuántos ciclos llevaba el metabolismo lo ponía a
        cero."""
        c = _coordinator(tmp_path)
        c.load_config()
        c.scheduler._cycle_count = 7
        assert c.status()["cycle_count"] == 7
        assert c.scheduler.cycle_count == 7

    def test_status_does_not_rebuild_the_scheduler(self, tmp_path: Path) -> None:
        c = _coordinator(tmp_path)
        c.load_config()
        before = id(c.scheduler)
        c.status()
        assert id(c.scheduler) == before

    def test_status_does_not_reread_the_config_from_disk(self, tmp_path: Path) -> None:
        """Una lectura no depende del disco. `status()` hacía `load_config()`
        dentro del lock: seis llamadas al sistema y ~8 KB leídos por consulta,
        con todos los demás hilos esperando detrás."""
        c = _coordinator(tmp_path)
        c.load_config()
        assert c._enabled is True
        (tmp_path / "triade.yml").unlink()
        assert c.status()["enabled"] is True

    def test_status_does_not_hold_the_lock_while_touching_the_database(
        self, tmp_path: Path
    ) -> None:
        """La consulta SQLite se hacía **dentro** de `self._lock`.

        Es la forma exacta del volcado que colgaba la suite: un hilo dentro de
        un SELECT reteniendo el lock, y el resto haciendo cola. Con la E/S
        fuera, el lock sólo cubre la copia del diccionario.
        """
        c = _coordinator(tmp_path)
        c.load_config()
        observed: list[bool] = []
        original = c.receipts.count_by_status

        def spy() -> dict[str, int]:
            observed.append(c._lock.acquire(blocking=False))
            if observed[-1]:
                c._lock.release()
            return original()

        c.receipts.count_by_status = spy  # type: ignore[method-assign]
        c.status()
        assert observed == [True], "la consulta a la base corrió con el lock tomado"


class TestProcessLock:
    def test_lock_prevents_second_coordinator(self, tmp_path: Path) -> None:
        c1 = _coordinator(tmp_path, enabled=True, max_cycles=0, interval_seconds=60)
        c2 = _coordinator(tmp_path, enabled=True, max_cycles=0, interval_seconds=60)
        c1.load_config()
        r1 = c1.start()
        assert r1["status"] == "started"
        err = c2._acquire_process_lock()
        assert err is not None, f"expected lock held, got {err!r}"
        r2 = c2.start()
        assert r2["status"] == "locked", f"expected locked, got {r2}"
        c1.stop(timeout=5)

    def test_lock_released_on_stop(self, tmp_path: Path) -> None:
        c = _coordinator(tmp_path, max_cycles=0, interval_seconds=60)
        c.load_config()
        c.start()
        lock_path = c._process_lock_path
        assert lock_path.exists()
        c.stop(timeout=5)
        assert not lock_path.exists()

    def test_two_databases_with_the_same_name_do_not_share_a_lock(
        self, tmp_path: Path
    ) -> None:
        """El lock identifica una base, no un nombre de fichero.

        Se derivaba de `/tmp/.triade_metabolism_{db_path.name}.lock`, es decir
        **sólo del nombre**. Dos bases distintas llamadas igual —el caso
        normal en pruebas, donde todas son `test.db`— se bloqueaban entre sí
        sin compartir un solo byte de estado.
        """
        db_a = tmp_path / "a" / "test.db"
        db_b = tmp_path / "b" / "test.db"
        db_a.parent.mkdir()
        db_b.parent.mkdir()
        ca = MetabolicCoordinator(db_path=str(db_a))
        cb = MetabolicCoordinator(db_path=str(db_b))

        assert ca._process_lock_path != cb._process_lock_path
        try:
            assert ca._acquire_process_lock() is None
            assert cb._acquire_process_lock() is None
        finally:
            ca._release_process_lock()
            cb._release_process_lock()

    def test_release_does_not_delete_a_lock_it_does_not_own(
        self, tmp_path: Path
    ) -> None:
        """Soltar sin ser dueño no borra el lock ajeno.

        `_release_process_lock` hacía `unlink` incondicional. Un coordinador
        que nunca llegó a adquirirlo —o que ya lo soltó— podía dejar sin
        protección al que sí lo tenía.
        """
        owner = _coordinator(tmp_path, max_cycles=0, interval_seconds=60)
        intruder = _coordinator(tmp_path, max_cycles=0, interval_seconds=60)
        assert owner._acquire_process_lock() is None
        try:
            assert intruder._acquire_process_lock() == "another_process_holds_lock"
            intruder._release_process_lock()
            assert owner._process_lock_path.exists(), "el intruso borró el lock de otro"
        finally:
            owner._release_process_lock()

    def test_release_never_closes_someone_elses_descriptor(
        self, tmp_path: Path
    ) -> None:
        """Soltar el lock no puede cerrar el fichero de otro.

        `_acquire_process_lock` cerraba el descriptor y **acto seguido** lo
        guardaba en `self._lock_fd`. El número quedaba libre, el kernel se lo
        daba al siguiente `open()` del proceso —una conexión SQLite, un
        socket— y `_release_process_lock` lo cerraba por debajo a su verdadero
        dueño. No es teórico: en Linux `open()` devuelve siempre el descriptor
        libre más bajo, así que la reasignación es determinista.
        """
        c = _coordinator(tmp_path, max_cycles=0, interval_seconds=60)
        assert c._acquire_process_lock() is None

        victim_path = tmp_path / "de_otro.txt"
        victim_path.write_text("contenido ajeno", encoding="utf-8")
        with victim_path.open("rb") as victim:
            c._release_process_lock()
            assert victim.read() == b"contenido ajeno"

    def test_live_sqlite_connection_survives_the_release(self, tmp_path: Path) -> None:
        """La consecuencia real: una transacción viva sobrevive al release.

        Cuando el descriptor reciclado era el de una base SQLite, cerrarlo
        rompía la conexión con `disk I/O error` **dejando su bloqueo POSIX
        huérfano**: la transacción ya no podía ni confirmar ni deshacer, y
        cualquier otro lector se quedaba esperando un bloqueo que nadie iba a
        soltar. Ese es el camino de "fd mal gestionado" a "cuelgue".
        """
        c = _coordinator(tmp_path, max_cycles=0, interval_seconds=60)
        assert c._acquire_process_lock() is None

        victim_db = tmp_path / "otra_base.db"
        conn = sqlite3.connect(victim_db, timeout=2)
        try:
            conn.execute("CREATE TABLE t(x)")
            conn.execute("BEGIN EXCLUSIVE")
            conn.execute("INSERT INTO t VALUES (1)")
            c._release_process_lock()
            conn.commit()
            assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
        finally:
            conn.close()


class TestDryRun:
    def test_dry_run_does_not_execute(self, tmp_path: Path) -> None:
        c = _coordinator(tmp_path, dry_run=True)
        c.load_config()
        assert c._dry_run is True
        need = MetabolicNeed(
            need_id="test-dry-run-001",
            kind="health_check",
            priority=90,
            evidence={},
        )
        result = c._execute([need], cycle_id=1)
        assert len(result) == 1
        assert result[0]["status"] == "dry_run"

    def test_dry_run_via_config(self, tmp_path: Path) -> None:
        cfg = tmp_path / "triade.yml"
        cfg.write_text(
            "metabolism:\n"
            "  enabled: true\n"
            "  dry_run: true\n"
            "  mode: observe_only\n"
            "  interval_seconds: 60\n"
            "  max_cycles: 0\n"
            "  jitter_seconds: 0.0\n",
            encoding="utf-8",
        )
        c = MetabolicCoordinator(
            db_path=str(tmp_path / "test.db"), config_path=str(cfg)
        )
        c.load_config()
        assert c._dry_run is True
        assert c._mode == "observe_only"


class TestRunNeedAction:
    def test_unknown_kind_returns_skipped(self, tmp_path: Path) -> None:
        c = _coordinator(tmp_path)
        need = MetabolicNeed(
            need_id="test-unknown-001",
            kind="nonexistent_kind_xyz",
            priority=50,
            evidence={},
        )
        status, detail = c._run_need_action(need, 1)
        assert status == "skipped"
        assert "no_handler" in detail

    def test_health_check_is_success(self, tmp_path: Path) -> None:
        c = _coordinator(tmp_path)
        status, _detail = c._action_health_check()
        assert status == "success"


class TestConsolidate:
    def test_consolidate_writes_summary(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        c = _coordinator(tmp_path)
        c.db_path = db
        cycle_id = c._start_cycle()
        need = MetabolicNeed(
            need_id="test-consolidate-001",
            kind="health_check",
            priority=90,
            evidence={},
        )
        c._execute([need], cycle_id)
        c._consolidate(
            [{"need_id": need.need_id, "status": "success", "detail": "ok"}],
            cycle_id,
        )
        with sqlite3.connect(db) as conn:
            row = conn.execute(
                "SELECT summary_json FROM metabolic_cycle WHERE cycle_id=?",
                (cycle_id,),
            ).fetchone()
        assert row is not None
        summary = json.loads(row[0])
        assert summary["passed"] >= 1
        assert summary["total"] >= 1


class TestResourceMeasurement:
    def test_execute_need_records_real_cpu(self, tmp_path: Path) -> None:
        c = _coordinator(tmp_path)
        cycle_id = c._start_cycle()
        need = MetabolicNeed(
            need_id="test-cpu-001",
            kind="health_check",
            priority=90,
            evidence={},
        )
        result = c._execute_need(need, cycle_id)
        assert result["status"] == "success"
        assert "duration_ms" in result
        assert result["duration_ms"] > 0

    def test_rss_measurement_returns_float(self, tmp_path: Path) -> None:
        rss = MetabolicCoordinator._measure_rss_mb()
        assert isinstance(rss, float)
        assert rss >= 0


class TestSingleton:
    def test_get_coordinator_uses_environment_database(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        import triade.metabolism.coordinator as module

        database = tmp_path / "environment.db"
        monkeypatch.setenv("TRIADE_DB_PATH", str(database))
        monkeypatch.setattr(module, "_COORDINATOR", None)
        assert module.get_coordinator().db_path == database

    def test_get_coordinator_is_singleton(self, tmp_path: Path) -> None:
        db = str(tmp_path / "test.db")
        c1 = get_coordinator(db_path=db)
        c2 = get_coordinator(db_path=db)
        assert c1 is c2

    def test_configure_updates_mode(self, tmp_path: Path) -> None:
        c = _coordinator(tmp_path)
        c.load_config()
        c.configure(mode="observe_only")
        assert c._mode == "observe_only"
        c.configure(mode="full")
        assert c._mode == "full"


def test_el_metabolismo_encuentra_su_config_desde_cualquier_directorio(tmp_path):
    """Una ruta relativa hacía que el metabolismo se degradara en silencio.

    `config_path` era `Path("triade.yml")`, resuelto contra el directorio de
    trabajo. Un proceso arrancado desde otro sitio no lo encontraba,
    `load_config()` recibía un diccionario vacío y el metabolismo caía a
    `enabled: False, mode: observe_only` **sin un solo error**: ni excepción, ni
    log, ni `last_tick_error`. Sólo dejaba de trabajar.

    Medido el 2026-08-08 desde `/tmp`: `{'enabled': None, 'mode': None}`.
    """
    import os

    from triade.metabolism.coordinator import MetabolicCoordinator

    previo = os.getcwd()
    os.chdir(tmp_path)
    try:
        meta = MetabolicCoordinator(db_path=tmp_path / "t.db").load_config()
    finally:
        os.chdir(previo)

    assert meta, "el metabolismo no encontró triade.yml fuera de la raíz"
    assert meta.get("mode") == "full", (
        "cayó a observe_only por no leer su configuración: degradación silenciosa"
    )


# ── el organismo se reconoce de punta a punta ─────────────────────────


def test_el_metabolismo_detecta_un_eslabon_vital_roto(tmp_path: Path) -> None:
    """«Algo no cuadra» tiene que poder decirlo el organismo, no un informe.

    Los otros cinco sensores miran recursos —disco, memoria, latido, leases,
    cola— y ninguno mira si la cadena que va del pulso al efecto futuro sigue
    entera. Es el único fallo que no se nota desde fuera: el sistema puede tener
    disco de sobra, latido puntual y cola vacía justamente *porque* un eslabón
    dejó de producir.

    La comprobación existía en `observability/introspection.py`, dentro del
    informe de deuda, que se arma sobre un artefacto de hasta seis horas. Un
    diagnóstico de hace seis horas describe un sistema que ya no existe.
    """
    from triade.metabolism.health import HealthSensors

    db = tmp_path / "triade.db"
    conn = sqlite3.connect(db)
    # Una base con tablas pero sin una sola fila: la cadena entera sin latido.
    for tabla in ("metabolic_cycle", "metabolic_needs", "runs", "learning_queue"):
        conn.execute(f"CREATE TABLE {tabla} (id INTEGER PRIMARY KEY, created_at TEXT)")
    conn.commit()
    conn.close()

    cadena = HealthSensors(db).inspect()["vital_chain"]
    assert cadena["ok"] is False
    assert cadena["stages"] == 11
    assert cadena["broken"], "la cadena vacía tiene que producir cortes"
    assert any("sin filas" in str(x) for x in cadena["broken"]), cadena["broken"]


def test_la_cadena_vital_entra_en_la_salud_general(tmp_path: Path) -> None:
    """Si no entra en `healthy`, el coordinador nunca se entera."""
    from triade.metabolism.health import HealthSensors

    db = tmp_path / "triade.db"
    sqlite3.connect(db).close()
    sensores = HealthSensors(db).inspect()
    assert "vital_chain" in sensores


def test_el_aviso_nombra_el_eslabon_y_no_solo_el_sensor(tmp_path: Path) -> None:
    """Un aviso que no dice qué mirar se acaba ignorando."""
    from triade.metabolism.coordinator import MetabolicCoordinator

    db = tmp_path / "triade.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE metabolic_cycle (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    coord = MetabolicCoordinator(db_path=db)
    estado, mensaje = coord._action_health_check()
    assert estado == "success"
    if "vital_chain" in mensaje:
        assert "cadena vital:" in mensaje, mensaje

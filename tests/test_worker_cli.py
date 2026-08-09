"""CLI de Triade Living Workers."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "triade_digimon.py"


def run_cli(*args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout)


def test_workers_cli_once_and_status(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    once = run_cli("workers", "--db", str(db_path), "--runs-dir", str(runs_dir), "once")
    status = run_cli(
        "workers", "--db", str(db_path), "--runs-dir", str(runs_dir), "status"
    )

    assert once["status"] == "completed"
    assert once["tasks_completed"] >= 1
    assert status["last_run"]["run_ref"] == once["run_ref"]


def test_workers_cli_start_is_bounded(tmp_path: Path) -> None:
    result = run_cli(
        "workers",
        "--db",
        str(tmp_path / "triade.db"),
        "--runs-dir",
        str(tmp_path / "runs"),
        "start",
        "--max-iterations",
        "2",
        "--sleep",
        "0",
    )

    assert result["status"] == "completed"
    assert result["iterations"] == 2
    # Cuántas tareas caben en dos ciclos depende de lo rápido que corran, no de
    # que la ejecución esté acotada, que es lo que esta prueba se llama a sí
    # misma. `== 1` falló en CI el 2026-08-09 con `assert 2 == 1` en #87 y #92,
    # mientras pasaba en #95 y #96 —ramas del mismo `main`— y localmente en las
    # tres ramas y con 2, 3 y 4 iteraciones.
    #
    # Se probaron y descartaron tres causas: clave de backup en el entorno de CI
    # (no la hay), más iteraciones dando más tareas (siempre 1 en local), y
    # `AdaptiveScheduler` leyendo la base de producción (recibe `db_path` de
    # `scheduler.py:20` y `worker_loop.py:230`). El discriminante exacto sigue
    # sin explicar; el log de CI muestra una parada de 7,5 minutos a mitad de
    # suite, así que hay contención de por medio.
    #
    # Lo que la prueba tiene que garantizar es que el worker acotado trabaja y
    # para cuando debe. Eso lo dicen `iterations`, `run_count` y que haya
    # trabajo hecho — no un número exacto de tareas.
    assert result["tasks_completed"] >= 1
    assert result["live_scheduler"]["jobs"]["dispatch"]["run_count"] == 2


def test_workers_cli_queue_events_doctor_and_stop(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    run_cli("workers", "--db", str(db_path), "--runs-dir", str(runs_dir), "once")

    queue = run_cli(
        "workers", "--db", str(db_path), "--runs-dir", str(runs_dir), "queue"
    )
    events = run_cli(
        "workers", "--db", str(db_path), "--runs-dir", str(runs_dir), "events"
    )
    doctor = run_cli(
        "workers", "--db", str(db_path), "--runs-dir", str(runs_dir), "doctor"
    )
    try:
        stopped = run_cli(
            "workers", "--db", str(db_path), "--runs-dir", str(runs_dir), "stop"
        )
    finally:
        stop_file = ROOT / ".triade_stop"
        if stop_file.exists():
            stop_file.unlink()

    assert queue["count"] >= 1
    assert events["count"] >= 1
    assert doctor["mode"] == "triade-living-workers"
    assert stopped["status"] == "stop_requested"

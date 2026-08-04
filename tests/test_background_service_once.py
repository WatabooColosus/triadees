"""Tests del servicio Living Workers."""

from __future__ import annotations

from pathlib import Path

from triade.workers.background_service import WorkerBackgroundService


def test_background_service_once_updates_status(tmp_path: Path) -> None:
    service = WorkerBackgroundService(
        db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs"
    )

    # El contrato de esta prueba es la persistencia del estado. Los handlers y
    # el pool concurrente tienen suites propias; dry-run evita depender de los
    # servicios y la configuración del host que ejecuta pytest.
    result = service.run_once(dry_run=True)
    status = service.status()

    assert result["status"] == "completed"
    assert status["last_run"]["run_ref"] == result["run_ref"]
    assert status["running"] is False

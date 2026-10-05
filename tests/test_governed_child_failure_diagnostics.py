"""Regresión: un fallo de handler nunca puede quedar sin diagnóstico.

El síntoma original era un `stderr.log` de 0 bytesaccompanied de
`child_exited_without_result:1` / `child_closed_pipe_without_result`: la
excepción escapaba de `_callable_child` porque su tipo no estaba en
`CHILD_EXECUTION_ERRORS`, el pipe se cerraba sin `send` y el traceback real
terminaba en el stderr del proceso API. En producción eso produjo ~140
dead-letters en 24h sin causa accionable.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.runtime.governed_task_executor import (
    CHILD_EXECUTION_ERRORS,
    GovernedTaskExecutor,
)
from triade.workers.worker_loop import WorkerLoop


class _Handler:
    """Handler con estado, como los bound methods del WorkerLoop real."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def raises_attribute_error(self, task, run_ref, task_dir, config) -> dict:
        # Mismo acceso que fallaba en producción: `task` llega y el handler lo
        # toca sin validar. Antes esto escapaba del hijo.
        return {"status": "completed", "target": task.payload.get("target")}

    def raises_custom_error(self, task, run_ref, task_dir, config) -> dict:
        # Una excepción propia tampoco estaba en la tupla.
        raise _CustomDomainError("domain rule violated")


class _CustomDomainError(Exception):
    pass


class _Task:
    """Debe vivir a nivel de módulo: `spawn` no puede picklear clases locales."""

    payload = {"target": "artifact.json"}


def test_attribute_error_is_captured_and_logged(tmp_path: Path) -> None:
    handler = _Handler(tmp_path / "x.db")
    artifact = tmp_path / "task"
    outcome = GovernedTaskExecutor(
        tmp_path / "quarantine"
    ).execute_callable(
        handler.raises_attribute_error,
        args=(None, "run-ref", str(artifact), None),
        timeout_seconds=60.0,
        artifact_dir=artifact,
    )

    assert outcome.status == "failed"
    assert "AttributeError" in str(outcome.error)
    assert "has no attribute 'payload'" in str(outcome.error)

    stderr = Path(outcome.stderr_ref)
    assert stderr.exists(), "stderr_ref debe existir para poder diagnosticar"
    content = stderr.read_text(encoding="utf-8", errors="replace")
    assert content.strip(), "stderr.log no puede quedar vacío en un fallo"
    assert "AttributeError" in content
    assert "Traceback" in content


def test_custom_exception_is_captured_and_logged(tmp_path: Path) -> None:
    handler = _Handler(tmp_path / "x.db")
    artifact = tmp_path / "task"
    outcome = GovernedTaskExecutor(
        tmp_path / "quarantine"
    ).execute_callable(
        handler.raises_custom_error,
        args=(None, "run-ref", str(artifact), None),
        timeout_seconds=60.0,
        artifact_dir=artifact,
    )

    assert outcome.status == "failed"
    assert "_CustomDomainError" in str(outcome.error)
    assert "domain rule violated" in str(outcome.error)

    content = Path(outcome.stderr_ref).read_text(encoding="utf-8", errors="replace")
    assert "_CustomDomainError" in content
    assert "Traceback" in content


def test_child_error_tuple_covers_common_types() -> None:
    """Los tipos que antes escapaban deben estar declarados explícitamente."""
    for exc_type in (
        AttributeError,
        IndexError,
        ArithmeticError,
        AssertionError,
        NameError,
        KeyError,
        TypeError,
        ValueError,
        OSError,
        RuntimeError,
    ):
        assert issubclass(exc_type, CHILD_EXECUTION_ERRORS), (
            f"{exc_type.__name__} debe estar en CHILD_EXECUTION_ERRORS; si no, "
            "el fallo escapa del hijo y stderr.log queda vacío."
        )


def test_bound_method_handler_round_trip(tmp_path: Path) -> None:
    """La forma de producción: bound method de un WorkerLoop con estado.

    Los tests previos usaban funciones a nivel de módulo, que sí son
    picklables con `spawn`. Un bound method exige además que el estado de la
    instancia sobreviva al pickle; esta ruta nunca estuvo cubierta.
    """
    db = tmp_path / "worker.db"
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    loop = WorkerLoop(
        db_path=db,
        runs_dir=runs,
        lock_file=runs / "w.lock",
        stop_file=runs / ".stop",
    )

    artifact = tmp_path / "task"
    outcome = loop.task_executor.execute_callable(
        loop._write_governed_text_artifact,
        args=(_Task(), "run-ref", str(artifact), None),
        timeout_seconds=60.0,
        artifact_dir=artifact,
    )
    assert outcome.status == "completed", f"error={outcome.error}"


def test_db_is_not_polluted_by_repro(tmp_path: Path) -> None:
    """ElExecutor no debe abrir la base viva durante la reproducción."""
    db = tmp_path / "guard.db"
    loop = WorkerLoop(
        db_path=db,
        runs_dir=tmp_path / "runs2",
        lock_file=tmp_path / "runs2" / "w.lock",
        stop_file=tmp_path / "runs2" / ".stop",
    )
    assert Path(loop.db_path) == db
    con = sqlite3.connect(db)
    con.close()
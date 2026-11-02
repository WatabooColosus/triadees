"""Contrato independiente para una reparación de clasificación de workers.

El módulo permanece inactivo en los tests ordinarios. El certificador
EngineeringEvolutionWorker activa este oráculo determinista *solo* al probar
la receta correspondiente en worktrees Git aislados. Los tests y su SHA
permanecen idénticos en A y B; jamás proceden del incidente ni del parche.
"""

import os

import pytest

from triade.workers.worker_loop import _should_learn_from_worker_outcome

pytestmark = pytest.mark.skipif(
    os.environ.get("TRIADE_FUNCTIONAL_REPAIR_PROBE")
    != "requested_cancellation_marked_failed",
    reason="oráculo reservado para ensayo funcional Git controlado",
)


def test_explicit_cancel_should_not_be_recorded_as_failed_learning():
    assert not _should_learn_from_worker_outcome(
        "failed", {"reason": "cancellation_requested"}
    )


def test_explicit_cancel_should_not_be_recorded_as_blocked_learning():
    assert not _should_learn_from_worker_outcome(
        "blocked", {"reason": "cancellation_requested"}
    )


def test_real_sql_failure_remains_a_learning_signal():
    assert _should_learn_from_worker_outcome(
        "failed", {"error": "sqlite_database_locked"}
    )


def test_unexpected_cancel_remains_a_learning_signal():
    assert _should_learn_from_worker_outcome(
        "cancelled", {"error": "unexpected_worker_termination"}
    )

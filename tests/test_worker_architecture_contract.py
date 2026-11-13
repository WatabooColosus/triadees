"""Gate que impide introducir tipos de tarea incompletos u huérfanos."""

from dataclasses import fields

import pytest

from triade.constitution.autonomy import OPERATION_REGISTRY, TASK_OPERATION
from triade.workers.architecture import (
    TASK_HANDLERS,
    TASK_PRODUCERS,
    WORKER_TASK_CONTRACTS,
    WorkerTaskContract,
    contract_for,
)
from triade.workers.concurrency import TASK_CONCURRENCY_POLICY
from triade.workers.contracts import WORKER_TASK_TYPES
from triade.workers.worker_loop import WorkerLoop

REQUIRED_FIELDS = {
    "task_type",
    "producer",
    "operation",
    "autonomy_level",
    "risk",
    "concurrency_lane",
    "exclusive_key",
    "handler",
    "terminal_states",
    "cooldown",
    "idempotency",
    "evidence",
    "timeout",
    "retry_policy",
}


def test_contract_schema_contains_every_required_field() -> None:
    assert {item.name for item in fields(WorkerTaskContract)} == REQUIRED_FIELDS


def test_every_task_type_has_exactly_one_complete_contract() -> None:
    assert set(WORKER_TASK_CONTRACTS) == set(WORKER_TASK_TYPES)
    for task_type, contract in WORKER_TASK_CONTRACTS.items():
        values = contract.to_dict()
        non_empty = REQUIRED_FIELDS - {"exclusive_key"}
        assert all(values[name] not in (None, "", (), []) for name in non_empty), (
            task_type
        )
        assert isinstance(contract.exclusive_key, tuple)
        assert contract.task_type == task_type
        assert contract.timeout > 0
        assert contract.retry_policy.max_attempts > 0


def test_zero_handlers_without_producer_and_zero_producers_without_handler() -> None:
    known = set(WORKER_TASK_TYPES)
    assert set(TASK_HANDLERS) == known == set(TASK_PRODUCERS)
    for task_type in known:
        assert hasattr(WorkerLoop, TASK_HANDLERS[task_type]), task_type


def test_every_operation_has_policy_and_every_task_has_concurrency_policy() -> None:
    known = set(WORKER_TASK_TYPES)
    assert set(TASK_OPERATION) == known
    assert set(TASK_CONCURRENCY_POLICY) == known
    assert all(operation in OPERATION_REGISTRY for operation in TASK_OPERATION.values())


def test_unknown_task_contract_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown_worker_task_type"):
        contract_for("handler_inventado")

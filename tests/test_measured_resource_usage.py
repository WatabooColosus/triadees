from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from triade.runtime.resource_ledger import (
    ResourceLedger,
    ResourceMeasurement,
    ResourceMeasurementCollector,
)


def test_resource_measurement_declares_source() -> None:
    collector = ResourceMeasurementCollector()
    time.sleep(0.01)
    usage = collector.finish()
    wall = next(
        item for item in usage.measurements if item.resource_name == "wall_time"
    )
    assert wall.measurement_type == "measured"
    assert wall.source == "time.monotonic"
    assert wall.value is not None and wall.value >= 0.01


def test_estimate_never_claims_measured(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    ResourceLedger(db_path).record(
        task_id="t", worker_id="w", cpu_seconds=2, success=True
    )
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT measurement_type,source FROM resource_measurements WHERE resource_name='cpu_seconds'"
        ).fetchone()
    assert row == ("estimated", "caller_reported")


def test_unavailable_resource_is_explicit() -> None:
    usage = ResourceMeasurementCollector().finish()
    gpu = next(
        item for item in usage.measurements if item.resource_name == "gpu_memory_peak"
    )
    assert gpu.measurement_type == "unavailable"
    assert gpu.value is None


def test_task_receipt_contains_resource_usage(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    ledger = ResourceLedger(db_path)
    usage = ResourceMeasurementCollector().finish()
    entry = ledger.record_usage(
        task_id="task", worker_id="worker", usage=usage, success=True
    )
    with sqlite3.connect(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM resource_measurements WHERE ledger_entry_id=?",
            (entry,),
        ).fetchone()[0]
    assert count == len(usage.measurements)


def test_no_fixed_fabricated_budget_consumption(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    ledger = ResourceLedger(db_path)
    ledger.record(task_id="task", worker_id="worker", success=True)
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM resource_measurements").fetchone()[0]
    assert count == 0


def test_unavailable_measurement_cannot_contain_value() -> None:
    try:
        ResourceMeasurement("gpu", 10, "MiB", "unavailable", "none", "start", "finish")
    except ValueError as exc:
        assert "cannot_have_value" in str(exc)
    else:
        raise AssertionError("unavailable measurement accepted a fabricated value")

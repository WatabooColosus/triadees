"""Runtime pressure admission and bounded fair drain accounting."""

from __future__ import annotations

import shutil
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from triade.runtime.resource_ledger import ResourceLedger


@dataclass(frozen=True, slots=True)
class PressureSnapshot:
    state: str
    reasons: tuple[str, ...]
    memory_available_mb: float | None
    disk_free_mb: float
    temperature_c: float | None


class RuntimeBackpressure:
    def __init__(
        self,
        ledger: ResourceLedger,
        *,
        disk_path: str | Path = ".",
        probe: Callable[[], PressureSnapshot] | None = None,
    ) -> None:
        self.ledger = ledger
        self.disk_path = Path(disk_path)
        self.probe = probe

    def snapshot(self) -> PressureSnapshot:
        if self.probe:
            return self.probe()
        free_mb = shutil.disk_usage(self.disk_path).free / 1024**2
        reasons: list[str] = []
        state = "normal"
        if free_mb < 512:
            state, reasons = "critical", ["disk_critical"]
        elif free_mb < 2048:
            state, reasons = "degraded", ["disk_low"]
        ledger_mode = self.ledger.policy()["mode"]
        if ledger_mode == "observe_only":
            state, reasons = "observe_only", [*reasons, "daily_budget_exhausted"]
        return PressureSnapshot(state, tuple(reasons), None, free_mb, None)

    def allows(self, task_type: str, *, effectful: bool) -> bool:
        pressure = self.snapshot()
        if pressure.state in {"critical", "observe_only"}:
            return task_type in {"pulse_check", "encrypted_backup"} and not effectful
        return not (pressure.state == "degraded" and effectful)


class QueueDrainBudget:
    def __init__(self, *, max_tasks: int, max_seconds: float, per_type: int) -> None:
        self.max_tasks = max(1, max_tasks)
        self.max_seconds = max(0.01, max_seconds)
        self.per_type = max(1, per_type)
        self.started = time.monotonic()
        self.total = 0
        self.by_type: Counter[str] = Counter()

    @property
    def exhausted(self) -> bool:
        return (
            self.total >= self.max_tasks
            or time.monotonic() - self.started >= self.max_seconds
        )

    @property
    def excluded_types(self) -> set[str]:
        return {name for name, count in self.by_type.items() if count >= self.per_type}

    def record(self, task_type: str) -> None:
        self.total += 1
        self.by_type[task_type] += 1

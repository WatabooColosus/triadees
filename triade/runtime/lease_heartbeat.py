"""Periodic lease renewal with generation fencing."""

from __future__ import annotations

from dataclasses import dataclass

from triade.runtime.task_leases import AutonomousTaskStore


@dataclass(slots=True)
class LeaseHeartbeat:
    store: AutonomousTaskStore
    task_id: str
    worker_id: str
    lease_generation: int
    lease_seconds: int

    @property
    def interval_seconds(self) -> float:
        return max(0.1, min(self.lease_seconds / 3, 15.0))

    def renew(self) -> bool:
        return self.store.renew(
            self.task_id,
            self.worker_id,
            self.lease_generation,
            lease_seconds=self.lease_seconds,
        )

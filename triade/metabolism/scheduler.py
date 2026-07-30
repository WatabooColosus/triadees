from __future__ import annotations

import random
import time
from typing import Any


class MetabolicScheduler:
    def __init__(
        self,
        interval_seconds: float = 30.0,
        jitter_seconds: float = 2.0,
        max_cycles: int = 0,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.jitter_seconds = jitter_seconds
        self.max_cycles = max_cycles
        self._cycle_count = 0
        self._stop_requested = False

    @property
    def cycle_count(self) -> int:
        return self._cycle_count

    def wait_for_next(self) -> bool:
        if self._stop_requested:
            return False
        if self.max_cycles > 0 and self._cycle_count >= self.max_cycles:
            return False
        jitter = random.uniform(0, self.jitter_seconds)
        time.sleep(self.interval_seconds + jitter)
        self._cycle_count += 1
        return not self._stop_requested

    def request_stop(self) -> None:
        self._stop_requested = True

    def snapshot(self) -> dict[str, Any]:
        return {
            "interval_seconds": self.interval_seconds,
            "jitter_seconds": self.jitter_seconds,
            "max_cycles": self.max_cycles,
            "cycle_count": self._cycle_count,
            "stop_requested": self._stop_requested,
        }

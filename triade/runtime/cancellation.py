"""Cooperative cancellation observed by supervisors and batch handlers."""

from __future__ import annotations

import threading
from collections.abc import Callable


class CancellationRequested(RuntimeError):
    pass


class CancellationToken:
    def __init__(self, external_check: Callable[[], bool] | None = None) -> None:
        self._event = threading.Event()
        self._external_check = external_check

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set() or bool(
            self._external_check and self._external_check()
        )

    def checkpoint(self) -> None:
        if self.cancelled:
            raise CancellationRequested("cancellation_requested")

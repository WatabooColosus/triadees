"""Registro vivo de nodos federados.

Este módulo separa la limpieza de nodos stale del servidor FastAPI principal.
Sirve para que la contabilidad de recursos no use nodos viejos como si fueran
recursos reales disponibles.
"""

from __future__ import annotations

import os
import threading
from typing import Any

from triade.federation.federation import Federation


DEFAULT_TTL_SECONDS = float(os.environ.get("TRIADE_NODE_ONLINE_TTL_SECONDS", "3"))
DEFAULT_SWEEP_SECONDS = float(os.environ.get("TRIADE_NODE_SWEEP_SECONDS", "1"))


class NodeLiveRegistry:
    """Barrido seguro de nodos sin heartbeat reciente."""

    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_result: dict[str, Any] = {}

    def sweep_once(self) -> dict[str, Any]:
        result = Federation().mark_stale_nodes(ttl_seconds=int(self.ttl_seconds))
        self.last_result = result
        return result

    def start(self, interval_seconds: float = DEFAULT_SWEEP_SECONDS) -> None:
        interval = max(1.0, float(interval_seconds))
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.sweep_once()
                except Exception as exc:
                    self.last_result = {"status": "error", "error": str(exc)}
                self._stop.wait(interval)

        self._thread = threading.Thread(target=loop, name="triade-node-live-registry", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


NODE_LIVE_REGISTRY = NodeLiveRegistry()


def sweep_live_nodes(ttl_seconds: float | None = None) -> dict[str, Any]:
    registry = NodeLiveRegistry(ttl_seconds=ttl_seconds or DEFAULT_TTL_SECONDS)
    return registry.sweep_once()

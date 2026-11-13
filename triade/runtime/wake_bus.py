"""Eventos locales para despertar runtimes al entrar trabajo nuevo."""

from __future__ import annotations

import threading
from pathlib import Path

_LOCK = threading.Lock()
_EVENTS: dict[str, threading.Event] = {}


def runtime_wake_event(db_path: str | Path) -> threading.Event:
    key = str(Path(db_path).resolve())
    with _LOCK:
        return _EVENTS.setdefault(key, threading.Event())


def wake_runtime(db_path: str | Path) -> None:
    runtime_wake_event(db_path).set()

"""Drop-in SQLite API with an explicit connection lifecycle.

The standard ``sqlite3.Connection`` context manager only commits or rolls back;
it does not close the connection.  Tríade historically treated it as an
OPEN -> USE -> COMMIT/ROLLBACK -> CLOSE contract, retaining file descriptors
under sustained work.  Productive code imports this module as ``sqlite3`` so
existing pragmas, row factories, exceptions and transaction semantics remain
unchanged while context-managed connections are closed deterministically.

Connections intentionally owned by a thread or service are unaffected: unless
they enter a ``with`` block, they stay open until their owner calls ``close``.
"""

from __future__ import annotations

import os
import resource
import sqlite3 as _stdlib_sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from sqlite3 import *
from types import TracebackType
from typing import Any, Literal, Self, cast

import psutil

_metrics_lock = threading.Lock()
_opened_total = 0
_closed_total = 0
_open_connections = 0


class ClosingConnection(_stdlib_sqlite3.Connection):
    """A SQLite connection that closes after context commit or rollback."""

    _triade_closed = False

    def __enter__(self) -> Self:
        super().__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        try:
            super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()
        return False

    def close(self) -> None:
        global _closed_total, _open_connections
        if self._triade_closed:
            return
        try:
            super().close()
        finally:
            self._triade_closed = True
            with _metrics_lock:
                _closed_total += 1
                _open_connections -= 1


def connect(  # type: ignore[no-redef]
    *args: Any, **kwargs: Any
) -> _stdlib_sqlite3.Connection:
    """Open an instrumented connection without changing SQLite configuration."""

    global _opened_total, _open_connections
    factory = kwargs.get("factory")
    if factory is not None and factory is not ClosingConnection:
        # A caller-supplied factory owns its lifecycle semantics.  There are no
        # such productive callers today, but preserving stdlib compatibility is
        # safer than silently replacing it.
        return _stdlib_sqlite3.connect(*args, **kwargs)
    kwargs["factory"] = ClosingConnection
    connection = _stdlib_sqlite3.connect(*args, **kwargs)
    with _metrics_lock:
        _opened_total += 1
        _open_connections += 1
    return connection


@contextmanager
def managed_connection(
    *args: Any, **kwargs: Any
) -> Iterator[_stdlib_sqlite3.Connection]:
    """Canonical OPEN -> USE -> COMMIT/ROLLBACK -> CLOSE context."""

    with connect(*args, **kwargs) as connection:
        yield connection


def connection_metrics() -> dict[str, int]:
    """Return process-local lifecycle counters without probing private state."""

    with _metrics_lock:
        return {
            "open_connections": _open_connections,
            "opened_total": _opened_total,
            "closed_total": _closed_total,
        }


def resource_metrics(database: str | Path) -> dict[str, int | float]:
    """Measure live process and SQLite resources from the operating system."""

    database_path = str(Path(database).resolve())
    sqlite_descriptors = 0
    try:
        process = psutil.Process()
        opened_files = process.open_files()
    except psutil.Error:
        # Some containerized runners expose a short-lived PID to psutil even
        # though the current process and its /proc entries are still usable.
        # Keep health endpoints observable instead of failing the request.
        process = None
        opened_files = []

    if process is not None:
        for opened in opened_files:
            if opened.path == database_path or opened.path.startswith(
                f"{database_path}-"
            ):
                sqlite_descriptors += 1
        process_file_descriptors = (
            process.num_fds()
            if hasattr(process, "num_fds")
            else cast(Any, process).num_handles()
        )
        rss_mb = round(process.memory_info().rss / (1024 * 1024), 2)
    else:
        fd_root = Path("/proc/self/fd")
        if fd_root.exists():
            for descriptor in fd_root.iterdir():
                try:
                    target = os.readlink(descriptor)
                except OSError:
                    continue
                if target == database_path or target.startswith(f"{database_path}-"):
                    sqlite_descriptors += 1
            process_file_descriptors = sum(1 for _ in fd_root.iterdir())
        else:
            process_file_descriptors = 0
        # Linux reports KiB; macOS reports bytes.  The fallback is only used
        # when psutil cannot identify the process, so keep the conversion
        # conservative and positive for health/readiness consumers.
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_mb = round(usage / (1024 * 1024), 2) if usage > 1024 * 1024 else round(usage / 1024, 2)
    return {
        **connection_metrics(),
        "db_file_descriptors": sqlite_descriptors,
        "process_file_descriptors": process_file_descriptors,
        "rss_mb": rss_mb,
    }

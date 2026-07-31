#!/usr/bin/env python3
"""Entrypoint foreground de workers para supervisores externos."""

from triade.memory.db_pragmas import ensure_durability_pragmas
from triade.workers.background_service import WorkerBackgroundService

if __name__ == "__main__":
    # Este proceso puede ser el primero en tocar la base (arranca en paralelo con
    # la API). Garantizar WAL aquí también evita que una base recién creada quede
    # en journal_mode 'delete' (P1-04). Idempotente.
    ensure_durability_pragmas()
    result = WorkerBackgroundService().start(
        max_iterations=1_000_000, sleep_seconds=60, task_timeout=30
    )
    if result.get("status") not in {"completed", "completed_with_errors", "stopped"}:
        raise SystemExit(1)

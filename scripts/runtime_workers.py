#!/usr/bin/env python3
"""Entrypoint foreground de workers para supervisores externos."""

from triade.workers.background_service import WorkerBackgroundService


if __name__ == "__main__":
    result = WorkerBackgroundService().start(max_iterations=1_000_000, sleep_seconds=60, task_timeout=30)
    if result.get("status") not in {"completed", "completed_with_errors", "stopped"}:
        raise SystemExit(1)

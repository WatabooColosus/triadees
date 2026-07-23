"""Servicio controlado para Triade Living Workers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.core.ollama_blood import check_ollama_blood

from .contracts import WorkerRunConfig
from .state_store import WorkerStateStore
from .task_queue import WorkerTaskQueue
from .worker_loop import WorkerLoop


class WorkerBackgroundService:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db", runs_dir: str | Path = "runs/background") -> None:
        self.db_path = Path(db_path)
        self.runs_dir = Path(runs_dir)
        self.lock_file = self.runs_dir / ".triade_workers.lock"
        self.stop_file = self.runs_dir / ".triade_stop"
        self.store = WorkerStateStore(db_path=self.db_path)
        self.queue = WorkerTaskQueue(db_path=self.db_path)

    def run_once(self, *, dry_run: bool = False, task_timeout: float = 30.0) -> dict[str, Any]:
        loop = WorkerLoop(db_path=self.db_path, runs_dir=self.runs_dir, lock_file=self.lock_file, stop_file=self.stop_file)
        config = WorkerRunConfig(max_iterations=1, sleep_seconds=0.0, task_timeout=task_timeout, dry_run=dry_run, once=True, daemon=False, runs_dir=str(self.runs_dir), lock_file=str(self.lock_file), stop_file=str(self.stop_file))
        return loop.run(config)

    def start(self, *, max_iterations: int = 5, sleep_seconds: float = 2.0, dry_run: bool = False,
              task_timeout: float = 30.0, enabled_task_types: list[str] | None = None) -> dict[str, Any]:
        loop = WorkerLoop(db_path=self.db_path, runs_dir=self.runs_dir, lock_file=self.lock_file, stop_file=self.stop_file)
        loop.clear_stop()
        config = WorkerRunConfig(max_iterations=max_iterations, sleep_seconds=sleep_seconds, task_timeout=task_timeout,
                                 dry_run=dry_run, once=False, daemon=True, runs_dir=str(self.runs_dir),
                                 lock_file=str(self.lock_file), stop_file=str(self.stop_file),
                                 enabled_task_types=list(enabled_task_types or []))
        return loop.run(config)

    def stop(self) -> dict[str, Any]:
        return WorkerLoop(db_path=self.db_path, runs_dir=self.runs_dir, lock_file=self.lock_file, stop_file=self.stop_file).request_stop()

    def status(self) -> dict[str, Any]:
        payload = self.store.status()
        blood = check_ollama_blood()
        payload["lock_file"] = str(self.lock_file)
        payload["stop_file"] = str(self.stop_file)
        payload["lock_file_active"] = self.lock_file.exists()
        payload["running"] = bool((payload.get("execution") or {}).get("alive"))
        payload["stop_requested"] = self.stop_file.exists()
        payload["ollama_blood_status"] = blood.get("status")
        payload["model_used"] = blood.get("reasoning_model")
        payload["degraded_mode"] = bool(blood.get("fallback_mode"))
        payload["cognitive_blood_active"] = bool(blood.get("cognitive_blood_active"))
        return payload

    def queue_status(self, status: str | None = None, limit: int = 50) -> dict[str, Any]:
        tasks = self.queue.list(status=status, limit=limit)
        return {"status": "ok", "count": len(tasks), "tasks": tasks}

    def events(self, limit: int = 50, run_ref: str | None = None) -> dict[str, Any]:
        events = self.store.list_events(limit=limit, run_ref=run_ref)
        return {"status": "ok", "count": len(events), "events": events}

    def doctor(self) -> dict[str, Any]:
        payload = self.store.doctor()
        payload["service"] = {"runs_dir": str(self.runs_dir), "safe_loop": True, "daemon_is_bounded": True}
        payload["ollama_blood"] = check_ollama_blood()
        return payload

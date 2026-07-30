"""Recoverable DB/filesystem completion protocol."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from triade.runtime.task_artifacts import CanonicalTaskArtifacts
from triade.runtime.task_leases import AutonomousTaskStore


class AtomicCompletionCoordinator:
    def __init__(self, store: AutonomousTaskStore) -> None:
        self.store = store

    def complete(
        self,
        *,
        task_id: str,
        worker_id: str,
        lease_generation: int,
        artifacts: CanonicalTaskArtifacts,
        staging_path: Path,
        event_recorder: Callable[[], None] | None = None,
    ) -> bool:
        staged_result = staging_path / "result.json"
        if not staged_result.is_file():
            return False
        final_ref = str(artifacts.path / "result.json")
        if not self.store.prepare_completion(
            task_id, worker_id, lease_generation, final_ref
        ):
            return False
        try:
            artifacts.publish(staging_path)
        except OSError:
            return False
        if event_recorder is not None:
            try:
                event_recorder()
            except (OSError, ImportError, RuntimeError, ValueError):
                return False
        return self.store.finalize_completion(
            task_id, worker_id, lease_generation, final_ref
        )

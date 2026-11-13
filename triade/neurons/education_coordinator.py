"""Baseline-first coordinator for functional neuron education."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triade.runtime.task_leases import AutonomousTaskStore
from triade.db import sqlite3


class EducationCoordinator:
    """Coordinate pre-probe, session creation and post-probe scheduling.

    The coordinator never creates a session until a verified pre task exists;
    task idempotency keys make retries safe.
    """

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.tasks = AutonomousTaskStore(self.db_path)
        migration = Path(__file__).resolve().parent.parent / "memory/migrations/040_education_coordination.sql"
        with sqlite3.connect(self.db_path, timeout=20) as conn:
            conn.executescript(migration.read_text(encoding="utf-8"))
            conn.commit()

    def request_baseline(
        self, *, neuron_id: int, case_id: str, correlation_id: str | None = None
    ) -> dict[str, Any]:
        key = f"functional-pre:{neuron_id}:{case_id}"
        task = self.tasks.enqueue(
            "neuron_functional_probe",
            {
                "neuron_id": neuron_id,
                "case_id": case_id,
                "phase": "pre",
                "correlation_id": correlation_id or uuid.uuid4().hex,
            },
            idempotency_key=key,
            priority=18,
            max_attempts=3,
        )
        task_id = task.get("task_id", task)
        self._record(f"pre:{neuron_id}:{case_id}", neuron_id, case_id, "pre", "baseline_requested", task_id=task_id)
        return {"status": "baseline_requested", "task_id": task_id}

    def request_post(
        self, *, session_id: str, neuron_id: int, case_id: str, correlation_id: str | None = None
    ) -> dict[str, Any]:
        key = f"functional-post:{session_id}:{case_id}"
        task = self.tasks.enqueue(
            "neuron_functional_probe",
            {
                "neuron_id": neuron_id,
                "case_id": case_id,
                "phase": "post",
                "session_id": session_id,
                "correlation_id": correlation_id or session_id,
            },
            idempotency_key=key,
            priority=22,
            max_attempts=3,
        )
        task_id = task.get("task_id", task)
        self._record(f"post:{session_id}:{case_id}", neuron_id, case_id, "post", "post_requested", task_id=task_id, session_id=session_id)
        return {"status": "post_requested", "task_id": task_id}

    def _record(self, coordination_id: str, neuron_id: int, case_id: str, phase: str, state: str, *, task_id: Any, session_id: str | None = None) -> None:
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db_path, timeout=20) as conn:
            conn.execute("""INSERT INTO neuron_education_coordination
                (coordination_id,neuron_id,case_id,session_id,phase,state,task_id,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(coordination_id) DO UPDATE SET state=excluded.state,task_id=excluded.task_id,updated_at=excluded.updated_at""",
                (coordination_id, neuron_id, case_id, session_id, phase, state, str(task_id), now, now))

    def record_run(self, *, neuron_id: int, case_id: str, phase: str, run_id: str, session_id: str | None = None) -> None:
        coordination_id = f"pre:{neuron_id}:{case_id}" if phase == "pre" else f"post:{session_id}:{case_id}"
        now = datetime.now(UTC).isoformat()
        state = "baseline_registered" if phase == "pre" else "post_requested"
        with sqlite3.connect(self.db_path, timeout=20) as conn:
            conn.execute("UPDATE neuron_education_coordination SET state=?,run_id=?,updated_at=? WHERE coordination_id=?", (state, run_id, now, coordination_id))

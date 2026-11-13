from __future__ import annotations

import json
from pathlib import Path

from triade.db import sqlite3
from triade.services.event_bus import list_recent_events, publish_event
from triade.workers.contracts import WorkerTask
from triade.workers.worker_loop import WorkerLoop


def test_worker_ollama_event_is_correlated_and_causal(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    loop = WorkerLoop(
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        lock_file=tmp_path / "lock",
        stop_file=tmp_path / "stop",
    )
    task = WorkerTask(task_type="goal_research", id="task-42")
    client = loop._observable_ollama_client(
        task,
        "worker-run-1",
        cognitive_function="learning_evaluation",
        artifact="distilled_claims",
        consumer="GovernedResearchWorker",
    )

    client._observe(
        {
            "operation": "generate",
            "requested_model": "qwen-requested",
            "model_used": "qwen-actual",
            "duration_ms": 12.5,
            "ok": True,
            "device_reported": "gpu",
            "size_vram": 1024,
        }
    )

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """SELECT run_ref, task_id, task_type, event_type, payload_json
               FROM worker_events ORDER BY id DESC LIMIT 1"""
        ).fetchone()
    assert row[:4] == (
        "worker-run-1",
        None,
        "goal_research",
        "ollama_call_completed",
    )
    payload = json.loads(row[4])["payload"]
    assert payload["task_id"] == "task-42"
    assert payload["run_ref"] == "worker-run-1"
    assert payload["worker"] == "living_worker"
    assert payload["cognitive_function"] == "learning_evaluation"
    assert payload["consumer"] == "GovernedResearchWorker"
    assert payload["effect"] == "available_to_task_handler"


def test_filtered_ollama_history_is_not_displaced_by_other_events(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "triade.db"
    publish_event("ollama_call_completed", "worker_loop", {"ok": True}, db_path=db_path)
    for index in range(3):
        publish_event("heartbeat", "runtime", {"index": index}, db_path=db_path)

    events = list_recent_events(
        limit=1, db_path=db_path, event_type="ollama_call_completed"
    )
    assert len(events) == 1
    assert events[0]["event_type"] == "ollama_call_completed"

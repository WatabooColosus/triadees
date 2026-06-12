"""Tests para NeuronMissionExecutor y su integración con WorkerLoop."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

from triade.core.neuron_missions import NeuronMission, NeuronMissionStore
from triade.workers.contracts import WorkerRunConfig, WorkerTask
from triade.workers.neuron_mission_executor import NeuronMissionExecutor
from triade.workers.worker_loop import WorkerLoop


def make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
    return db_path


def create_mission(
    db_path: Path,
    *,
    allowed_actions: list[str] | None = None,
    status: str = "experimental",
) -> int:
    store = NeuronMissionStore(db_path=db_path)
    return store.create_mission(
        NeuronMission(
            neuron_id=11,
            title="Observabilidad de misiones",
            mission="Detectar ciclos trazables de trabajo neuronal",
            domain="observability",
            status=status,
            allowed_sources=["worker", "run"],
            allowed_actions=allowed_actions or ["observe", "diagnose", "propose_learning"],
        )
    )


def learning_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM learning_queue").fetchone()[0])


def identity_rows(db_path: Path) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT key, value, category, confidence FROM identity_core ORDER BY id").fetchall()


def test_execute_creates_cycle_evidence_and_score(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    mission_id = create_mission(db_path)
    result = NeuronMissionExecutor(db_path=db_path).execute(
        mission_id=mission_id,
        run_ref="run-exec-1",
        task_payload={"mission_id": mission_id},
        task_dir=tmp_path / "task",
        config=WorkerRunConfig(task_timeout=5),
    )

    store = NeuronMissionStore(db_path=db_path)
    assert result["status"] == "completed"
    assert result["mission_id"] == mission_id
    assert result["cycle_id"] > 0
    assert result["evidence_id"] > 0
    assert result["score_id"] > 0
    assert store.list_cycles(mission_id)
    assert store.list_evidence(mission_id)
    assert store.latest_score(mission_id) is not None
    assert result["policy"]["shell"] is False
    assert result["policy"]["network"] is False
    assert result["stable_memory_written"] is False


def test_execute_creates_learning_candidate_when_allowed(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    mission_id = create_mission(db_path, allowed_actions=["observe", "diagnose", "propose_learning"])
    result = NeuronMissionExecutor(db_path=db_path).execute(
        mission_id=mission_id,
        run_ref="run-learn-1",
        task_payload={"mission_id": mission_id},
        task_dir=tmp_path / "task",
        config=WorkerRunConfig(task_timeout=5),
    )

    assert result["decision"] == "learning_candidate_proposed"
    assert result["learning_candidate"]["source_type"] == "tool"
    assert result["learning_candidate"]["source_ref"] == f"mission:{mission_id}:run:run-learn-1"
    assert learning_count(db_path) == 1


def test_execute_does_not_create_learning_candidate_without_allowed_action(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    mission_id = create_mission(db_path, allowed_actions=["observe", "diagnose"])
    result = NeuronMissionExecutor(db_path=db_path).execute(
        mission_id=mission_id,
        run_ref="run-no-learn-1",
        task_payload={"mission_id": mission_id},
        task_dir=tmp_path / "task",
        config=WorkerRunConfig(task_timeout=5),
    )

    assert result["decision"] == "learning_proposal_not_allowed"
    assert result["learning_candidate"] is None
    assert learning_count(db_path) == 0


def test_worker_loop_experimental_neuron_activity_uses_payload_mission_id(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    mission_id = create_mission(db_path)
    loop = WorkerLoop(db_path=db_path, runs_dir=tmp_path / "runs")
    task = WorkerTask(task_type="experimental_neuron_activity", payload={"mission_id": mission_id}, id=42)

    result = loop._experimental_neuron_activity(
        task,
        run_ref="run-worker-mission",
        task_dir=tmp_path / "task-worker",
        config=WorkerRunConfig(task_timeout=5),
    )

    assert result["status"] == "completed"
    assert result["mission_id"] == mission_id
    assert result["cycle_id"] > 0
    assert result["evidence_id"] > 0
    assert result["score_id"] > 0
    assert result["stable_memory_written"] is False
    assert result["qualia"]["published"] is True
    assert learning_count(db_path) == 1


def test_executor_does_not_touch_identity_core(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    before = identity_rows(db_path)
    mission_id = create_mission(db_path)

    NeuronMissionExecutor(db_path=db_path).execute(
        mission_id=mission_id,
        run_ref="run-identity",
        task_payload={"mission_id": mission_id},
        task_dir=tmp_path / "task-identity",
        config=WorkerRunConfig(task_timeout=5),
    )

    assert identity_rows(db_path) == before


def test_executor_uses_no_shell_or_network(tmp_path: Path, monkeypatch) -> None:
    db_path = make_db(tmp_path)
    mission_id = create_mission(db_path)

    def fail_shell(*args, **kwargs):
        raise AssertionError("shell execution is forbidden")

    def fail_network(*args, **kwargs):
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(subprocess, "run", fail_shell)
    monkeypatch.setattr(subprocess, "Popen", fail_shell)
    monkeypatch.setattr("socket.create_connection", fail_network)

    result = NeuronMissionExecutor(db_path=db_path).execute(
        mission_id=mission_id,
        run_ref="run-safe-local",
        task_payload={"mission_id": mission_id},
        task_dir=tmp_path / "task-safe",
        config=WorkerRunConfig(task_timeout=5),
    )

    assert result["status"] == "completed"
    assert result["policy"] == {
        "shell": False,
        "network": False,
        "identity_core_modified": False,
        "stable_memory_written": False,
    }

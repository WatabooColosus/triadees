"""Tests de backfill y operación de misiones neuronales existentes."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from apps.single_port_app import app
import apps.routes.api as routes_api
from triade.core.neuron_activity_store import NeuronActivityStore
from triade.core.neuron_creator import NeuronSpec
from triade.core.neuron_missions import NeuronMissionStore
from triade.core.neuron_registry import NeuronRegistry
from triade.core.neuron_trainer import NeuronTrainingResult
from triade.workers.mission_planner import MissionPlanner
from triade.workers.neuron_mission_backfill import backfill_neuron_missions, neuron_missions_doctor
from triade.workers.worker_loop import WorkerLoop
from triade.workers.contracts import WorkerTask, WorkerRunConfig


def make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
    return db_path


def register_neuron(db_path: Path, *, name: str, status: str, domain: str = "observability") -> dict:
    registry = NeuronRegistry(db_path=db_path)
    spec = NeuronSpec(
        name=name,
        mission=f"Mission for {name}",
        domain=domain,
        rules=["rule-1", "rule-2", "rule-3", "rule-4", "rule-5"],
        triggers=["trigger-1"],
        inputs_allowed=["runs"],
        outputs_allowed=["diagnosis"],
        forbidden_actions=["write_stable_memory", "modify_identity_core", "shell", "network"],
        success_metrics=["cycles", "evidence"],
        evidence_required=["run", "worker"],
        status=status,
        created_by="tests",
    )
    neuron_id = registry.register(spec)
    registry.update_status(name, status)
    return registry.get_neuron(name)


def add_training_and_activity(db_path: Path, neuron: dict) -> None:
    registry = NeuronRegistry(db_path=db_path)
    registry.store_training(
        int(neuron["id"]),
        NeuronTrainingResult(
            name=str(neuron["name"]),
            score=0.88,
            status="stable",
            strengths=["training"],
            warnings=[],
            recommendations=["keep tracing"],
        ),
    )
    registry.update_status(str(neuron["name"]), "stable")

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs (run_id, source, user_input, status) VALUES (?, ?, ?, ?)",
            ("run-stable-evidence", "tests", "input", "ok"),
        )
    activity_store = NeuronActivityStore(db_path=db_path)
    activity_store.record_run_activity(
        "run-stable-evidence",
        {
            "active": True,
            "activations": [
                {
                    "neuron_id": neuron["id"],
                    "name": neuron["name"],
                    "domain": neuron["domain"],
                    "status": "stable",
                    "policy": "manual_test",
                    "output": {"diagnosis": ["ok"], "test_plan": ["next"]},
                }
            ],
        },
    )


def mission_ids(store: NeuronMissionStore, neuron_id: int) -> list[int]:
    return [int(m.id) for m in store.get_missions_by_neuron(neuron_id) if m.id is not None]


def test_backfill_creates_missions_and_is_idempotent(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)

    experimental = register_neuron(db_path, name="exp-neuron", status="experimental")
    stable = register_neuron(db_path, name="stable-neuron", status="stable")
    add_training_and_activity(db_path, stable)
    rejected = register_neuron(db_path, name="rejected-neuron", status="rejected")

    before_identity = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM identity_core").fetchone()[0]
    before_semantic = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM semantic_memory").fetchone()[0]

    first = backfill_neuron_missions(db_path=db_path, runs_dir=tmp_path / "runs", limit=20)
    assert first["created_count"] == 2
    assert first["skipped_ineligible_count"] == 0

    exp_mission = store.get_missions_by_neuron(int(experimental["id"]))[0]
    stable_mission = store.get_missions_by_neuron(int(stable["id"]))[0]
    assert exp_mission.status == "experimental"
    assert stable_mission.status == "stable"
    assert "worker" in exp_mission.allowed_sources
    assert "worker" in stable_mission.allowed_sources
    assert "request_stable_promotion" in stable_mission.allowed_actions
    assert "modify_identity_core" not in exp_mission.allowed_actions
    assert "write_stable_memory" not in stable_mission.allowed_actions
    assert not mission_ids(store, int(rejected["id"]))

    second = backfill_neuron_missions(db_path=db_path, runs_dir=tmp_path / "runs", limit=20)
    assert second["created_count"] == 0
    assert second["skipped_existing_count"] >= 2

    after_identity = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM identity_core").fetchone()[0]
    after_semantic = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM semantic_memory").fetchone()[0]
    assert after_identity == before_identity
    assert after_semantic == before_semantic


def test_mission_planner_agendas_mission_id_for_active_missions(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    neuron = register_neuron(db_path, name="planner-neuron", status="experimental")
    backfill_neuron_missions(db_path=db_path, runs_dir=tmp_path / "runs", limit=20)

    planner = MissionPlanner(db_path=db_path)
    tasks = planner.plan_cycle()
    mission_tasks = [task for task in tasks if task.task_type == "experimental_neuron_activity"]

    assert mission_tasks
    payload = mission_tasks[0].payload
    assert payload["mission_id"]
    assert payload["neuron_id"] == neuron["id"]
    assert mission_tasks[0].reason
    assert mission_tasks[0].source
    assert mission_tasks[0].planner_score > 0


def test_worker_loop_executes_executor_when_mission_id_present(tmp_path: Path, monkeypatch) -> None:
    db_path = make_db(tmp_path)
    neuron = register_neuron(db_path, name="worker-neuron", status="experimental")
    mission = backfill_neuron_missions(db_path=db_path, runs_dir=tmp_path / "runs", limit=20)["created"][0]

    captured: dict[str, object] = {}

    def fake_execute(self, mission_id, run_ref, task_payload, task_dir, config):
        captured["mission_id"] = mission_id
        captured["run_ref"] = run_ref
        captured["task_payload"] = task_payload
        captured["task_dir"] = str(task_dir)
        captured["task_timeout"] = config.task_timeout
        return {
            "status": "completed",
            "mission_id": mission_id,
            "cycle_id": 1,
            "evidence_id": 2,
            "score_id": 3,
            "diagnosis": "ok",
            "observation": "ok",
            "proposed_learning": "",
            "evidence_refs": ["mission:1"],
            "score_components": {"a": 1},
            "composite_score": 0.9,
            "learning_candidate": None,
            "decision": "observed_scored",
            "stable_memory_written": False,
            "policy": {"shell": False, "network": False, "identity_core_modified": False, "stable_memory_written": False},
        }

    monkeypatch.setattr("triade.workers.neuron_mission_executor.NeuronMissionExecutor.execute", fake_execute)

    loop = WorkerLoop(db_path=db_path, runs_dir=tmp_path / "runs")
    result = loop._experimental_neuron_activity(
        WorkerTask(task_type="experimental_neuron_activity", payload={"mission_id": mission["id"], "neuron_id": neuron["id"]}, id=9),
        run_ref="run-worker-1",
        task_dir=tmp_path / "task",
        config=WorkerRunConfig(task_timeout=5),
    )

    assert captured["mission_id"] == mission["id"]
    assert result["stable_memory_written"] is False
    assert result["qualia"]["published"] is True


def test_backfill_doctor_reports_counts_and_learning_candidates(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    neuron = register_neuron(db_path, name="doctor-neuron", status="experimental")
    backfill_neuron_missions(db_path=db_path, runs_dir=tmp_path / "runs", limit=20)

    doctor = neuron_missions_doctor(db_path=db_path, runs_dir=tmp_path / "runs", limit=20)
    assert doctor["total_neurons"] >= 1
    assert doctor["total_missions"] >= 1
    assert doctor["missions_by_status"]["experimental"] >= 1
    assert doctor["missions_without_cycles"] >= 1
    assert doctor["ready_to_execute_count"] >= 1
    assert isinstance(doctor["learning_candidates"], list)


def test_neuron_mission_api_routes_are_wired(monkeypatch) -> None:
    monkeypatch.setattr(routes_api, "backfill_neuron_missions", lambda **kwargs: {"status": "ok", "created_count": 1, "policy": {"stable_memory_written": False}})
    monkeypatch.setattr(routes_api, "neuron_missions_doctor", lambda **kwargs: {"status": "ok", "total_missions": 1, "policy": {"identity_core_protected": True}})

    client = TestClient(app)
    backfill = client.post("/api/neuron_missions/backfill")
    doctor = client.get("/api/neuron_missions/doctor")

    assert backfill.status_code == 200
    assert backfill.json()["created_count"] == 1
    assert doctor.status_code == 200
    assert doctor.json()["total_missions"] == 1

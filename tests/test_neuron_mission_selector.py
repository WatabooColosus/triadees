"""Tests para el selector DB-backed de misiones relevantes."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from apps.single_port_app import app
from triade.core.contracts import InputPacket, MemoryPacket, CrystalPacket, SignalPacket
from triade.core.neuron_creator import NeuronSpec
from triade.core.neuron_registry import NeuronRegistry
from triade.core.neuron_missions import NeuronMission, NeuronMissionStore
from triade.core.neuron_mission_selector import select_relevant_missions
from triade.core.run_neuron_orchestrator import orchestrate_run_neurons
from triade.workers.contracts import WorkerRunConfig, WorkerTask
from triade.workers.neuron_mission_backfill import backfill_neuron_missions
from triade.workers.worker_loop import WorkerLoop


def make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
    return db_path


def register_neuron(db_path: Path, *, name: str, status: str, domain: str) -> dict:
    registry = NeuronRegistry(db_path=db_path)
    spec = NeuronSpec(
        name=name,
        mission=f"Misión {name}",
        domain=domain,
        rules=["rule-1", "rule-2", "rule-3"],
        triggers=["trigger-1"],
        inputs_allowed=["runs"],
        outputs_allowed=["diagnosis"],
        forbidden_actions=["modify_identity_core", "write_stable_memory", "shell", "network"],
        success_metrics=["cycles", "evidence"],
        evidence_required=["run", "worker"],
        status=status,
        created_by="tests",
    )
    registry.register(spec)
    registry.update_status(name, status)
    return registry.get_neuron(name)


def test_select_relevant_missions_filters_status(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)
    store.create_mission(NeuronMission(
        neuron_id=1,
        title="stable-keep",
        mission="Monitorea el sistema de memoria.",
        domain="memory",
        status="stable",
    ))
    store.create_mission(NeuronMission(
        neuron_id=2,
        title="rejected-skip",
        mission="No debe pasar.",
        domain="memory",
        status="rejected",
    ))
    store.create_mission(NeuronMission(
        neuron_id=3,
        title="paused-skip",
        mission="No debe pasar.",
        domain="memory",
        status="paused",
    ))

    result = select_relevant_missions(
        user_input="memoria operativa",
        domain="memory",
        db_path=db_path,
        limit=10,
    )

    selected_statuses = {item["status"] for item in result["selected"]}
    assert selected_statuses <= {"candidate", "experimental", "stable"}
    assert all(item["status"] != "rejected" for item in result["selected"])
    assert all(item["status"] != "paused" for item in result["selected"])
    assert any(item["status"] == "stable" for item in result["selected"])
    assert any(item["status"] == "rejected" for item in result["rejected"])
    assert any(item["status"] == "paused" for item in result["rejected"])


def test_select_relevant_missions_domain_match(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)
    store.create_mission(NeuronMission(
        neuron_id=1,
        title="mem-domain",
        mission="Gestiona memoria semántica.",
        domain="memory",
        status="experimental",
    ))
    store.create_mission(NeuronMission(
        neuron_id=2,
        title="other-domain",
        mission="Gestiona router.",
        domain="router",
        status="experimental",
    ))

    result = select_relevant_missions(user_input="estado interno", domain="memory", db_path=db_path, limit=5)
    assert result["selected"]
    assert result["selected"][0]["domain"] == "memory"
    assert result["selected"][0]["relevance_score"] >= result["selected"][-1]["relevance_score"]


def test_select_relevant_missions_keyword_match(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)
    store.create_mission(NeuronMission(
        neuron_id=1,
        title="keyword-mission",
        mission="Auditar memoria y evitar contradicciones.",
        domain="observability",
        status="experimental",
    ))
    store.create_mission(NeuronMission(
        neuron_id=2,
        title="noise-mission",
        mission="Procesar otro flujo.",
        domain="observability",
        status="experimental",
    ))

    result = select_relevant_missions(
        user_input="crear una neurona para auditar memoria y evitar contradicciones",
        domain="observability",
        db_path=db_path,
        limit=5,
    )

    assert result["selected"][0]["title"] == "keyword-mission" or result["selected"][0]["mission"].startswith("Auditar memoria")
    assert result["selected"][0]["reason"]
    assert "keyword_match" in result["selected"][0]["reason"] or "domain_match" in result["selected"][0]["reason"]


def test_selector_does_not_modify_identity_core(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)
    store.create_mission(NeuronMission(
        neuron_id=1,
        title="identity-scope",
        mission="Solo lectura.",
        domain="system",
        status="stable",
    ))
    with sqlite3.connect(db_path) as conn:
        before = conn.execute("SELECT COUNT(*) FROM identity_core").fetchone()[0]

    result = select_relevant_missions(user_input="estado", domain="system", db_path=db_path, limit=5)
    assert result["policy"]["selector_is_read_only"] is True

    with sqlite3.connect(db_path) as conn:
        after = conn.execute("SELECT COUNT(*) FROM identity_core").fetchone()[0]
    assert before == after


def test_relevant_missions_endpoint_and_alias_are_read_only(monkeypatch, tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    registry = NeuronRegistry(db_path=db_path)
    registry.register(NeuronSpec(
        name="api-mission",
        mission="Auditar memoria.",
        domain="observability",
        rules=["r1", "r2", "r3"],
        status="experimental",
        created_by="tests",
    ))

    def fake_select_relevant_missions(**kwargs):
        return {
            "status": "ok",
            "count": 1,
            "selected": [
                {
                    "id": 1,
                    "title": "api-mission",
                    "mission": "Auditar memoria.",
                    "domain": "observability",
                    "status": "experimental",
                    "schedule_hint": "every_cycle",
                    "relevance_score": 0.99,
                    "reason": "domain_match; keyword_match",
                }
            ],
            "rejected": [],
            "policy": {
                "active_status_only": True,
                "no_identity_core_modification": True,
                "selector_is_read_only": True,
            },
        }

    monkeypatch.setattr("triade.core.neuron_mission_selector.select_relevant_missions", fake_select_relevant_missions)

    client = TestClient(app)
    resp = client.get("/api/neurons/missions/relevant", params={"query": "memoria", "domain": "observability"})
    alias = client.get("/api/system/neurons/missions/relevant", params={"query": "memoria", "domain": "observability"})

    assert resp.status_code == 200
    assert alias.status_code == 200
    assert resp.json()["status"] == "ok"
    assert alias.json()["policy"]["selector_is_read_only"] is True


def test_run_orchestrator_uses_relevant_missions(tmp_path: Path, monkeypatch) -> None:
    db_path = make_db(tmp_path)
    registry = NeuronRegistry(db_path=db_path)
    registry.register(NeuronSpec(
        name="orchestrator-mission",
        mission="Auditar memoria y evitar contradicciones.",
        domain="observability",
        rules=["r1", "r2", "r3"],
        status="stable",
        created_by="tests",
    ))

    mission_store = NeuronMissionStore(db_path=db_path)
    backfill_neuron_missions(db_path=db_path, runs_dir=tmp_path / "runs", limit=10)
    mission_id = mission_store.get_missions_by_neuron(int(registry.get_neuron("orchestrator-mission")["id"]))[0].id

    monkeypatch.setattr(
        "triade.core.run_neuron_orchestrator.select_relevant_missions",
        lambda **kwargs: {
            "status": "ok",
            "count": 0,
            "selected": [],
            "rejected": [
                {"id": mission_id, "title": "orchestrator-mission", "status": "stable", "reason": "blocked for test"}
            ],
            "policy": {"active_status_only": True, "no_identity_core_modification": True, "selector_is_read_only": True},
        },
    )
    monkeypatch.setattr(
        "triade.core.run_neuron_orchestrator.run_experimental_neurons",
        lambda **kwargs: {"active": False, "count": 0, "contributions_count": 0, "contributions": []},
    )

    input_packet = InputPacket(user_input="estado interno", source="tests", context={"semantic_domain": "observability"})
    signals = SignalPacket(run_id=input_packet.run_id, intent="conversation", tone="neutral", urgency="low", risk="low")
    memory = MemoryPacket(run_id=input_packet.run_id)
    crystal = CrystalPacket(run_id=input_packet.run_id)
    output = type("Output", (), {"memory_diff": {}})()

    result = orchestrate_run_neurons(
        db_path=db_path,
        input_packet=input_packet,
        signals=signals,
        memory=memory,
        crystal=crystal,
        neuron_proposal=None,
        post_run_learning={},
        output_gate={"coherence": {}, "deduplication": {}, "source_labels": {}},
        output=output,
        edge_usage={"used_edge": False, "accepted": False},
    )

    assert output.memory_diff["relevant_missions"] == []
    assert output.memory_diff["mission_selection_policy"]["selector_is_read_only"] is True
    assert result["relevant_missions"] == []
    assert result["mission_selection_policy"]["selector_is_read_only"] is True


def test_worker_loop_blocks_irrelevant_mission(tmp_path: Path, monkeypatch) -> None:
    db_path = make_db(tmp_path)
    neuron = register_neuron(db_path, name="worker-skip-neuron", status="experimental", domain="observability")
    mission_store = NeuronMissionStore(db_path=db_path)
    mission_id = backfill_neuron_missions(db_path=db_path, runs_dir=tmp_path / "runs", limit=10)["created"][0]["id"]

    monkeypatch.setattr(
        "triade.core.neuron_mission_selector.select_relevant_missions",
        lambda **kwargs: {
            "status": "ok",
            "count": 0,
            "selected": [],
            "rejected": [{"id": mission_id, "title": "blocked", "status": "experimental", "reason": "irrelevant"}],
            "policy": {"active_status_only": True, "no_identity_core_modification": True, "selector_is_read_only": True},
        },
    )

    def _boom(*args, **kwargs):
        raise AssertionError("NeuronMissionExecutor no debe ejecutarse si la misión es irrelevante")

    monkeypatch.setattr("triade.workers.neuron_mission_executor.NeuronMissionExecutor.execute", _boom)

    loop = WorkerLoop(db_path=db_path, runs_dir=tmp_path / "runs")
    result = loop._experimental_neuron_activity(
        WorkerTask(
            task_type="experimental_neuron_activity",
            payload={
                "mission_id": mission_id,
                "neuron_id": neuron["id"],
                "query": "pregunta irrelevante",
                "domain": "unrelated",
            },
            id=11,
        ),
        run_ref="run-relevance-block",
        task_dir=tmp_path / "task",
        config=WorkerRunConfig(task_timeout=5),
    )

    assert result["status"] == "blocked"
    assert result["decision"] == "blocked_by_relevance"
    assert result["stable_memory_written"] is False
    assert result["mission_selection"]["count"] == 0

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from apps.single_port_app import app
import apps.routes.api as api_module
from triade.core.contracts import utc_now
from triade.core.bodega import Bodega
from triade.core.internal_runtime import InternalRuntimeSupervisor, build_runtime_heartbeat
from triade.core.learning_journal import build_learning_journal
from triade.core.neuron_missions import NeuronMission, NeuronMissionStore
from triade.core.neuron_nutrition import run_neuron_nutrition_cycle
from triade.learning.pipeline import LearningPipeline
from triade.services.event_bus import publish_event


def _init_db(db_path: Path) -> None:
    Bodega(db_path=db_path)
    LearningPipeline(db_path=db_path)
    NeuronMissionStore(db_path=db_path)


def _seed_runtime_mission(db_path: Path, *, status: str = "experimental") -> int:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO neurons (name, mission, domain, status, created_by) VALUES (?, ?, ?, ?, ?)",
            ("pulse-neuron", "Nutrir contexto y producir evidencia local.", "runtime", status, "test"),
        )
        neuron_id = int(conn.execute("SELECT id FROM neurons WHERE name = ?", ("pulse-neuron",)).fetchone()[0])
    store = NeuronMissionStore(db_path=db_path)
    return store.create_mission(
        NeuronMission(
            neuron_id=neuron_id,
            title="pulse-neuron",
            mission="Nutrir contexto y producir evidencia local.",
            domain="runtime",
            allowed_sources=["worker", "runs", "qualia_bus", "neuron_activity"],
            allowed_actions=["observe", "diagnose", "propose_learning"],
            status=status,
        )
    )


def test_learning_journal_counts_candidates(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    _init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO neuron_work_cycles (mission_id, neuron_id, cycle_type, input_summary, output_summary, evidence_refs_json, duration_ms, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 1, "mission_work", "input", "output", "[]", 12, "completed", utc_now()),
        )
        conn.execute(
            "INSERT INTO neuron_evidence (mission_id, neuron_id, evidence_type, source, content, refs_json, score, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 1, "mission_cycle", "worker", "evidence", "[]", 0.9, utc_now()),
        )
        conn.execute(
            """INSERT INTO learning_queue
            (candidate_id, source_type, source_ref, title, content, normalized_summary, domain, risk_level, confidence, utility, status, verification_notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("cand-1", "tool", "run:1", "c1", "content", "content", "runtime", "low", 0.0, 0.0, "candidate", "{}", utc_now(), utc_now()),
        )
        conn.execute(
            """INSERT INTO learning_queue
            (candidate_id, source_type, source_ref, title, content, normalized_summary, domain, risk_level, confidence, utility, status, verification_notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("cand-2", "tool", "run:2", "c2", "content", "content", "runtime", "low", 0.6, 0.7, "evaluated", "{}", utc_now(), utc_now()),
        )
        conn.execute(
            """INSERT INTO learning_queue
            (candidate_id, source_type, source_ref, title, content, normalized_summary, domain, risk_level, confidence, utility, status, verification_notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("cand-3", "tool", "run:3", "c3", "content", "content", "runtime", "low", 0.7, 0.8, "verified", "{}", utc_now(), utc_now()),
        )
        conn.execute(
            """INSERT INTO learning_queue
            (candidate_id, source_type, source_ref, title, content, normalized_summary, domain, risk_level, confidence, utility, status, verification_notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("cand-4", "tool", "run:4", "c4", "content", "content", "runtime", "low", 0.8, 0.8, "consolidated", "{}", utc_now(), utc_now()),
        )
        conn.execute(
            """INSERT INTO learning_queue
            (candidate_id, source_type, source_ref, title, content, normalized_summary, domain, risk_level, confidence, utility, status, verification_notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("cand-5", "tool", "run:5", "c5", "content", "content", "runtime", "low", 0.0, 0.0, "rejected", "{}", utc_now(), utc_now()),
        )
    publish_event("runtime_cycle_start", "test", {"mode": "full_local"}, db_path=db_path, run_ref="test")
    publish_event("runtime_cycle_complete", "test", {"mode": "full_local"}, db_path=db_path, run_ref="test")

    journal = build_learning_journal(db_path=db_path, since_hours=24, limit=10)

    assert journal["status"] == "ok"
    assert journal["cycles_last_24h"] >= 1
    assert journal["evidence_created"] >= 1
    assert journal["candidates_created"] >= 1
    assert journal["candidates_evaluated"] >= 1
    assert journal["candidates_verified"] >= 1
    assert journal["candidates_consolidated"] >= 1
    assert journal["candidates_rejected"] >= 1
    assert journal["truth"].startswith("Aprender significa")


def test_neuron_nutrition_creates_evidence(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    _init_db(db_path)
    mission_id = _seed_runtime_mission(db_path)

    result = run_neuron_nutrition_cycle(db_path=db_path, runs_dir=runs_dir, mode="execute_missions", limit=5)
    store = NeuronMissionStore(db_path=db_path)
    cycles = store.list_cycles(mission_id, limit=10)
    evidence = store.list_evidence(mission_id, limit=10)
    score = store.latest_score(mission_id)
    candidates = LearningPipeline(db_path=db_path).list_candidates(limit=20)

    assert result["status"] == "ok"
    assert result["missions_selected"] >= 1
    assert result["missions_executed"] >= 1
    assert result["evidence_created"] >= 1
    assert result["stable_memory_written"] is False
    assert result["identity_core_modified"] is False
    assert cycles
    assert evidence
    assert score is not None
    assert any(item.get("source_ref", "").startswith("mission:") for item in candidates)


def test_neuron_nutrition_does_not_modify_identity_core(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    _init_db(db_path)
    _seed_runtime_mission(db_path)

    with sqlite3.connect(db_path) as conn:
        before_identity = int(conn.execute("SELECT COUNT(*) FROM identity_core").fetchone()[0])
        before_stable = int(conn.execute("SELECT COUNT(*) FROM semantic_memory WHERE status = 'stable'").fetchone()[0])

    result = run_neuron_nutrition_cycle(db_path=db_path, runs_dir=runs_dir, mode="execute_missions", limit=5)

    with sqlite3.connect(db_path) as conn:
        after_identity = int(conn.execute("SELECT COUNT(*) FROM identity_core").fetchone()[0])
        after_stable = int(conn.execute("SELECT COUNT(*) FROM semantic_memory WHERE status = 'stable'").fetchone()[0])

    assert result["identity_core_modified"] is False
    assert before_identity == after_identity
    assert before_stable == after_stable


def test_runtime_heartbeat_returns_activity(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    _init_db(db_path)
    _seed_runtime_mission(db_path)
    run_neuron_nutrition_cycle(db_path=db_path, runs_dir=runs_dir, mode="execute_missions", limit=5)
    publish_event("runtime_cycle_start", "test", {"mode": "execute_missions"}, db_path=db_path, run_ref="test-heartbeat")
    publish_event("runtime_cycle_complete", "test", {"mode": "execute_missions"}, db_path=db_path, run_ref="test-heartbeat")

    heartbeat = build_runtime_heartbeat(db_path=db_path, runs_dir=runs_dir, since_hours=24, limit=10)

    assert heartbeat["status"] == "ok"
    assert heartbeat["cycles_last_24h"] >= 1
    assert heartbeat["neurons_nourished_last_24h"] >= 1
    assert heartbeat["runtime_continuity_score"] > 0
    assert heartbeat["learning_activity_summary"]["missions_executed"] >= 1


def test_runtime_learning_journal_endpoint(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    _init_db(db_path)
    monkeypatch.setattr(api_module, "build_learning_journal", lambda since_hours=24, limit=50: build_learning_journal(db_path=db_path, since_hours=since_hours, limit=limit))

    client = TestClient(app)
    response = client.get("/api/runtime/learning-journal")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "truth" in body


def test_runtime_heartbeat_endpoint(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    _init_db(db_path)
    _seed_runtime_mission(db_path)
    run_neuron_nutrition_cycle(db_path=db_path, runs_dir=runs_dir, mode="execute_missions", limit=5)
    publish_event("runtime_cycle_start", "test", {"mode": "execute_missions"}, db_path=db_path, run_ref="test-heartbeat")
    publish_event("runtime_cycle_complete", "test", {"mode": "execute_missions"}, db_path=db_path, run_ref="test-heartbeat")
    monkeypatch.setattr(
        api_module,
        "build_runtime_heartbeat",
        lambda since_hours=24, limit=50: build_runtime_heartbeat(db_path=db_path, runs_dir=runs_dir, since_hours=since_hours, limit=limit),
    )

    client = TestClient(app)
    response = client.get("/api/runtime/heartbeat")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["cycles_last_24h"] >= 1
    assert body["neurons_nourished_last_24h"] >= 1


def test_runtime_neuron_nutrition_endpoint(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    _init_db(db_path)
    _seed_runtime_mission(db_path)
    monkeypatch.setattr(
        api_module,
        "run_neuron_nutrition_cycle",
        lambda mode="observe_only", limit=5: run_neuron_nutrition_cycle(db_path=db_path, runs_dir=runs_dir, mode=mode, limit=limit),
    )

    client = TestClient(app)
    response = client.get("/api/runtime/neuron-nutrition")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["identity_core_modified"] is False


def test_full_local_does_not_consolidate_without_gates(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    _init_db(db_path)
    _seed_runtime_mission(db_path)

    supervisor = InternalRuntimeSupervisor(db_path=db_path, runs_dir=runs_dir)
    result = supervisor.run_once(mode="full_local")
    doctor = LearningPipeline(db_path=db_path).doctor()

    assert result["status"] == "ok"
    assert doctor["candidates_by_status"]["consolidated"] == 0

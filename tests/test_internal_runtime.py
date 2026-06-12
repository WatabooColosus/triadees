from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.core.internal_runtime import get_internal_runtime_supervisor
from triade.core.living_report import build_living_report
from triade.core.neuron_missions import NeuronMission, NeuronMissionStore
from triade.learning.pipeline import LearningPipeline
from triade.core.bodega import Bodega


def _init_db(db_path: Path) -> None:
    Bodega(db_path=db_path)
    LearningPipeline(db_path=db_path)
    NeuronMissionStore(db_path=db_path)


def _seed_gap_run(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO runs (run_id, source, user_input, status) VALUES (?, ?, ?, ?)",
            ("run-gap", "test", "gap de memoria", "created"),
        )


def _seed_experimental_mission(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO neurons (name, mission, domain, status, created_by)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("runtime-neuron", "Auditar memoria interna y proponer aprendizaje trazable.", "runtime", "experimental", "test"),
        )
        neuron_id = int(conn.execute("SELECT id FROM neurons WHERE name = ?", ("runtime-neuron",)).fetchone()[0])
    store = NeuronMissionStore(db_path=db_path)
    mission_id = store.create_mission(
        NeuronMission(
            neuron_id=neuron_id,
            title="runtime-neuron",
            mission="Auditar memoria interna y proponer aprendizaje trazable.",
            domain="runtime",
            allowed_sources=["worker", "runs", "qualia_bus", "neuron_activity"],
            allowed_actions=["observe", "diagnose", "propose_learning"],
            status="experimental",
        )
    )
    return mission_id


def test_runtime_default_is_observe_only(tmp_path):
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    _init_db(db_path)
    supervisor = get_internal_runtime_supervisor(db_path=db_path, runs_dir=runs_dir)
    snapshot = supervisor.snapshot()
    assert snapshot["mode"] == "observe_only"
    assert snapshot["enabled"] is False


def test_runtime_observe_only_does_not_create_learning(tmp_path):
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    _init_db(db_path)
    _seed_gap_run(db_path)
    supervisor = get_internal_runtime_supervisor(db_path=db_path, runs_dir=runs_dir)
    before = len(LearningPipeline(db_path=db_path).list_candidates(limit=50))
    result = supervisor.run_once(mode="observe_only")
    after = len(LearningPipeline(db_path=db_path).list_candidates(limit=50))
    assert result["status"] == "ok"
    assert result["mode"] == "observe_only"
    assert before == after == 0


def test_runtime_execute_missions_creates_cycle_evidence_and_score(tmp_path):
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    _init_db(db_path)
    _seed_gap_run(db_path)
    mission_id = _seed_experimental_mission(db_path)
    supervisor = get_internal_runtime_supervisor(db_path=db_path, runs_dir=runs_dir)

    result = supervisor.run_once(mode="execute_missions")

    store = NeuronMissionStore(db_path=db_path)
    cycles = store.list_cycles(mission_id, limit=10)
    evidence = store.list_evidence(mission_id, limit=10)
    score = store.latest_score(mission_id)
    candidates = LearningPipeline(db_path=db_path).list_candidates(limit=50)

    assert result["status"] == "ok"
    assert result["services"]["mission_service"]["status"] == "ok"
    assert cycles, "la misión debe registrar al menos un ciclo"
    assert evidence, "la misión debe registrar evidencia"
    assert score is not None, "la misión debe registrar score"
    assert any(row.get("source_ref", "").startswith("mission:") for row in candidates)


def test_runtime_full_local_does_not_touch_identity_core(tmp_path):
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    _init_db(db_path)
    _seed_gap_run(db_path)
    mission_id = _seed_experimental_mission(db_path)

    with sqlite3.connect(db_path) as conn:
        before = int(conn.execute("SELECT COUNT(*) FROM identity_core").fetchone()[0])

    supervisor = get_internal_runtime_supervisor(db_path=db_path, runs_dir=runs_dir)
    result = supervisor.run_once(mode="full_local")

    with sqlite3.connect(db_path) as conn:
        after = int(conn.execute("SELECT COUNT(*) FROM identity_core").fetchone()[0])

    report = build_living_report(db_path=db_path, runs_dir=runs_dir, limit=10)

    assert result["status"] == "ok"
    assert before == after
    assert report["status"] == "ok"
    assert "learning_doctor" in report["summary"]


from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.core.bodega import Bodega
from triade.core.internal_runtime import get_internal_runtime_supervisor
from triade.core.neuron_missions import NeuronMission, NeuronMissionStore
from triade.learning.pipeline import LearningPipeline
from triade.services.event_bus import list_recent_events


def _init_db(db_path: Path) -> None:
    Bodega(db_path=db_path)
    LearningPipeline(db_path=db_path)
    NeuronMissionStore(db_path=db_path)


def _seed_runtime_mission(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO neurons (name, mission, domain, status, created_by) VALUES (?, ?, ?, ?, ?)",
            ("service-neuron", "Supervisar estado interno.", "runtime", "experimental", "test"),
        )
        neuron_id = int(conn.execute("SELECT id FROM neurons WHERE name = ?", ("service-neuron",)).fetchone()[0])
    store = NeuronMissionStore(db_path=db_path)
    return store.create_mission(
        NeuronMission(
            neuron_id=neuron_id,
            title="service-neuron",
            mission="Supervisar estado interno.",
            domain="runtime",
            allowed_sources=["worker", "runs", "qualia_bus", "neuron_activity"],
            allowed_actions=["observe", "diagnose", "propose_learning"],
            status="experimental",
        )
    )


def test_supervisor_creates_internal_events(tmp_path):
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    _init_db(db_path)
    supervisor = get_internal_runtime_supervisor(db_path=db_path, runs_dir=runs_dir)

    result = supervisor.run_once(mode="observe_only")
    events = list_recent_events(limit=20, db_path=db_path)

    assert result["status"] == "ok"
    assert any(event.get("event_type") == "runtime_cycle_start" for event in events)
    assert any(event.get("event_type") == "runtime_cycle_complete" for event in events)


def test_supervisor_maps_governed_work_modes_to_runtime_levels(tmp_path):
    supervisor = get_internal_runtime_supervisor(
        db_path=tmp_path / "triade.db",
        runs_dir=tmp_path / "runs",
    )

    assert supervisor._normalize_mode("light_background") == "learn_candidates"
    assert supervisor._normalize_mode("balanced_background") == "execute_missions"
    assert supervisor._normalize_mode("full_local_guarded") == "full_local"


def test_mission_service_plans_active_missions(tmp_path):
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    _init_db(db_path)
    _seed_runtime_mission(db_path)

    supervisor = get_internal_runtime_supervisor(db_path=db_path, runs_dir=runs_dir)
    result = supervisor.run_once(mode="execute_missions")

    assert result["services"]["mission_service"]["status"] == "ok"
    assert result["counters"]["tasks_planned"] > 0
    assert result["counters"]["tasks_executed"] > 0

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.core.bodega import Bodega
from triade.core.internal_runtime import InternalRuntimeSupervisor
from triade.core.living_report import build_living_report
from triade.core.neuron_missions import NeuronMission, NeuronMissionStore
from triade.learning.pipeline import LearningPipeline


def _init_db(db_path: Path) -> None:
    Bodega(db_path=db_path)
    LearningPipeline(db_path=db_path)
    NeuronMissionStore(db_path=db_path)


def _seed_runtime_mission(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO neurons (name, mission, domain, status, created_by) VALUES (?, ?, ?, ?, ?)",
            ("bg-neuron", "Producir aprendizaje sin chat.", "runtime", "experimental", "test"),
        )
        neuron_id = int(conn.execute("SELECT id FROM neurons WHERE name = ?", ("bg-neuron",)).fetchone()[0])
    store = NeuronMissionStore(db_path=db_path)
    store.create_mission(
        NeuronMission(
            neuron_id=neuron_id,
            title="bg-neuron",
            mission="Producir aprendizaje sin chat.",
            domain="runtime",
            allowed_sources=["worker", "runs", "qualia_bus", "neuron_activity"],
            allowed_actions=["observe", "diagnose", "propose_learning"],
            status="experimental",
        )
    )


def test_runtime_runs_without_chat_and_reports_live_thinking(tmp_path):
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    _init_db(db_path)
    _seed_runtime_mission(db_path)
    supervisor = InternalRuntimeSupervisor(db_path=db_path, runs_dir=runs_dir)

    result = supervisor.run_once(mode="full_local")
    report = build_living_report(db_path=db_path, runs_dir=runs_dir, limit=10)

    with sqlite3.connect(db_path) as conn:
        identity_rows = int(conn.execute("SELECT COUNT(*) FROM identity_core").fetchone()[0])
        stable_memory_rows = int(conn.execute("SELECT COUNT(*) FROM semantic_memory WHERE status = 'stable'").fetchone()[0])

    assert result["status"] == "ok"
    assert report["is_thinking_without_chat"] is True
    assert report["runtime_enabled"] is False
    assert identity_rows >= 0
    assert stable_memory_rows >= 0


from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.core.central import Central
from triade.core.contracts import InputPacket, SignalPacket, MemoryPacket, CrystalPacket, PlanPacket
from triade.core.context_engine import build_living_context_for_chat
from triade.core.bodega import Bodega
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
            ("context-neuron", "Mantener contexto interno vivo.", "runtime", "experimental", "test"),
        )
        neuron_id = int(conn.execute("SELECT id FROM neurons WHERE name = ?", ("context-neuron",)).fetchone()[0])
    store = NeuronMissionStore(db_path=db_path)
    store.create_mission(
        NeuronMission(
            neuron_id=neuron_id,
            title="context-neuron",
            mission="Mantener contexto interno vivo.",
            domain="runtime",
            allowed_sources=["worker", "runs", "qualia_bus", "neuron_activity"],
            allowed_actions=["observe", "diagnose", "propose_learning"],
            status="experimental",
        )
    )


def test_context_engine_includes_runtime_state(tmp_path):
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    _init_db(db_path)
    _seed_runtime_mission(db_path)

    context = build_living_context_for_chat("estado runtime y misiones", db_path=db_path, runs_dir=runs_dir, limit=5)
    assert context["status"] == "ok"
    assert context["internal_context"]["missions"]["active_count"] == 1
    assert "runtime" in context["internal_context"]
    assert "qualia" in context["internal_context"]
    assert context["memory_context"]["status"] == "ok"


def test_central_uses_living_context_without_repeating_previous_answer(tmp_path):
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    _init_db(db_path)
    _seed_runtime_mission(db_path)
    context = build_living_context_for_chat("estado runtime y misiones", db_path=db_path, runs_dir=runs_dir, limit=5)

    packet = InputPacket(
        user_input="cuántas misiones tienes?",
        source="test",
        context={"triade_operational_awareness": context["internal_context"]},
    )
    response = Central._operational_awareness_response("Tríade Ω", packet)

    assert "misiones_actives=1" in response
    assert "runtime interno reporta" in response


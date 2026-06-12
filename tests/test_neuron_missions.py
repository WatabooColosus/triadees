"""Tests del sistema de misiones neuronales."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from triade.core.neuron_missions import (
    NeuronMission,
    NeuronWorkCycle,
    NeuronEvidence,
    NeuronScore,
    NeuronMissionStore,
)


def make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
    return db_path


def test_create_and_get_mission(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)

    mission = NeuronMission(
        neuron_id=1,
        title="Investigar edge computing",
        mission="Analizar patrones deedge computing en dispositivos móviles",
        domain="federation_android_edge",
        allowed_sources=["worker", "federation"],
        allowed_actions=["observe", "diagnose"],
    )
    mission_id = store.create_mission(mission)
    assert mission_id > 0

    loaded = store.get_mission(mission_id)
    assert loaded is not None
    assert loaded.title == "Investigar edge computing"
    assert loaded.domain == "federation_android_edge"
    assert loaded.allowed_sources == ["worker", "federation"]
    assert loaded.status == "candidate"


def test_list_missions_by_status(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)

    store.create_mission(NeuronMission(title="M1", mission="m1", status="candidate"))
    store.create_mission(NeuronMission(title="M2", mission="m2", status="experimental"))
    store.create_mission(NeuronMission(title="M3", mission="m3", status="candidate"))

    candidates = store.list_missions(status="candidate")
    assert len(candidates) == 2

    experimental = store.list_missions(status="experimental")
    assert len(experimental) == 1


def test_update_mission_status(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)

    mission_id = store.create_mission(NeuronMission(title="T", mission="m"))
    assert store.update_mission_status(mission_id, "experimental")

    loaded = store.get_mission(mission_id)
    assert loaded is not None
    assert loaded.status == "experimental"


def test_update_mission_metrics(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)

    mission_id = store.create_mission(NeuronMission(title="T", mission="m"))
    metrics = {"cycles_completed": 5, "evidence_count": 12}
    assert store.update_mission_metrics(mission_id, metrics)

    loaded = store.get_mission(mission_id)
    assert loaded is not None
    assert loaded.metrics["cycles_completed"] == 5
    assert loaded.metrics["evidence_count"] == 12


def test_record_and_list_cycles(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)

    mission_id = store.create_mission(NeuronMission(title="T", mission="m"))

    cycle = NeuronWorkCycle(
        mission_id=mission_id,
        neuron_id=1,
        cycle_type="observation",
        input_summary="Pulso del sistema",
        output_summary="Neurona activada",
        evidence_refs=["run-001", "run-002"],
        duration_ms=150,
    )
    cycle_id = store.record_cycle(cycle)
    assert cycle_id > 0

    cycles = store.list_cycles(mission_id)
    assert len(cycles) == 1
    assert cycles[0].input_summary == "Pulso del sistema"
    assert cycles[0].evidence_refs == ["run-001", "run-002"]


def test_record_and_list_evidence(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)

    mission_id = store.create_mission(NeuronMission(title="T", mission="m"))

    evidence = NeuronEvidence(
        mission_id=mission_id,
        neuron_id=1,
        evidence_type="diagnosis",
        source="worker",
        content="La neurona detectó patrón de uso en horario laboral",
        refs=["run-003"],
        score=0.75,
    )
    ev_id = store.record_evidence(evidence)
    assert ev_id > 0

    evidence_list = store.list_evidence(mission_id)
    assert len(evidence_list) == 1
    assert evidence_list[0].score == 0.75
    assert evidence_list[0].source == "worker"


def test_record_and_get_score(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)

    mission_id = store.create_mission(NeuronMission(title="T", mission="m"))

    score = NeuronScore(
        mission_id=mission_id,
        neuron_id=1,
        score_type="composite",
        value=0.82,
        components={"activation": 0.9, "evidence": 0.7, "learning": 0.85},
    )
    store.record_score(score)

    latest = store.latest_score(mission_id)
    assert latest is not None
    assert latest.value == 0.82
    assert latest.components["activation"] == 0.9


def test_get_missions_by_neuron(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)

    store.create_mission(NeuronMission(neuron_id=5, title="M1", mission="m1"))
    store.create_mission(NeuronMission(neuron_id=5, title="M2", mission="m2"))
    store.create_mission(NeuronMission(neuron_id=99, title="M3", mission="m3"))

    missions = store.get_missions_by_neuron(5)
    assert len(missions) == 2
    assert all(m.neuron_id == 5 for m in missions)


def test_mission_to_dict_contains_lists(tmp_path: Path) -> None:
    mission = NeuronMission(
        title="T",
        mission="m",
        allowed_sources=["a", "b"],
        allowed_actions=["x", "y"],
        metrics={"k": "v"},
    )
    d = mission.to_dict()
    assert d["allowed_sources"] == ["a", "b"]
    assert d["allowed_actions"] == ["x", "y"]
    assert d["metrics"] == {"k": "v"}

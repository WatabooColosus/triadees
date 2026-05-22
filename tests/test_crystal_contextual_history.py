"""Tests de aislamiento contextual del Cristal Morfológico 1.8F."""

from __future__ import annotations

import json

from triade.core.bodega import Bodega
from triade.core.contracts import InputPacket, MemoryPacket, SignalPacket
from triade.core.crystal import Crystal
from triade.core.runner import TriadeRunner


def test_comparison_basis_prefers_project_neuron() -> None:
    packet = InputPacket(
        user_input="Continuar tarea",
        source="single-port-ui",
        context={"project_id": "xiaos", "active_neuron": "neurona-xiaos"},
        run_id="run-context",
    )

    basis = TriadeRunner._build_comparison_basis(packet, intent="build_or_update")

    assert basis["context_scope"] == "project_neuron"
    assert basis["context_key"] == "project_neuron|intent=build_or_update|project_id=xiaos|active_neuron=neurona-xiaos"
    assert basis["project_id"] == "xiaos"
    assert basis["active_neuron"] == "neurona-xiaos"


def test_comparison_basis_defaults_to_source_intent() -> None:
    packet = InputPacket(user_input="Hola", source="chat-ui", run_id="run-default")

    basis = TriadeRunner._build_comparison_basis(packet, intent="conversation")

    assert basis["context_scope"] == "source_intent"
    assert basis["context_key"] == "source_intent|intent=conversation|source=chat-ui"


def test_bodega_filters_crystal_history_by_context_key(tmp_path) -> None:
    bodega = Bodega(db_path=tmp_path / "triade.db")
    signals_a = SignalPacket(run_id="run-a", intent="conversation", tone="neutral", urgency="low", risk="low")
    signals_b = SignalPacket(run_id="run-b", intent="conversation", tone="neutral", urgency="low", risk="low")
    basis_a = {"context_scope": "project", "context_key": "project|intent=conversation|project_id=a", "source": "test", "intent": "conversation", "project_id": "a"}
    basis_b = {"context_scope": "project", "context_key": "project|intent=conversation|project_id=b", "source": "test", "intent": "conversation", "project_id": "b"}

    bodega.create_run(InputPacket(user_input="A", source="test", run_id="run-a"))
    crystal_a = Crystal().regulate(signals_a, MemoryPacket(run_id="run-a", confidence=0.8), comparison_basis=basis_a)
    bodega.store_crystal(crystal_a)
    bodega.create_run(InputPacket(user_input="B", source="test", run_id="run-b"))
    crystal_b = Crystal().regulate(signals_b, MemoryPacket(run_id="run-b", confidence=0.8), comparison_basis=basis_b)
    bodega.store_crystal(crystal_b)

    only_a = bodega.list_recent_crystals(context_key=basis_a["context_key"])
    only_b = bodega.list_recent_crystals(context_key=basis_b["context_key"])

    assert [item["run_id"] for item in only_a] == ["run-a"]
    assert [item["run_id"] for item in only_b] == ["run-b"]


def test_runner_starts_baseline_for_new_project_and_continues_same_project(tmp_path) -> None:
    runner = TriadeRunner(runs_dir=tmp_path / "runs", db_path=tmp_path / "triade.db", use_ollama=False)
    context_a = {"project_id": "proyecto-a", "context_scope": "project"}
    context_b = {"project_id": "proyecto-b", "context_scope": "project"}

    first_a = runner.run("Inicio proyecto A", source="test", context=context_a)
    second_a = runner.run("Continuidad proyecto A", source="test", context=context_a)
    first_b = runner.run("Inicio proyecto B", source="test", context=context_b)

    assert first_a["crystal_temporal_state"]["status"] == "baseline"
    assert second_a["crystal_temporal_state"]["history_window"] == 1
    assert first_b["crystal_temporal_state"]["status"] == "baseline"
    assert first_b["crystal_temporal_state"]["history_window"] == 0
    assert first_a["crystal_temporal_state"]["context_key"] != first_b["crystal_temporal_state"]["context_key"]

    payload_b = json.loads((tmp_path / "runs" / first_b["run_id"] / "crystal.json").read_text(encoding="utf-8"))
    assert payload_b["context_scope"] == "project"
    assert payload_b["comparison_basis"]["project_id"] == "proyecto-b"

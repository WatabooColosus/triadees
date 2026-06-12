"""Fase B · propuesta auditable de neuronas dentro del ciclo run()."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.core.neuron_registry import NeuronRegistry
from triade.core.runner import TriadeRunner


def make_runner(tmp_path: Path) -> TriadeRunner:
    return TriadeRunner(runs_dir=tmp_path / "runs", db_path=tmp_path / "triade.db", use_ollama=False)


def test_build_intent_proposes_candidate_without_activation(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    result = runner.run(
        "crea una neurona para el café Lengua Negra Cold Brew",
        context={"active_neuron": "lengua-negra"},
    )

    proposal = result["neuron_proposal"]
    assert proposal is not None
    assert proposal["registered_as"] == "candidate"
    assert proposal["activation"] == "auto_approved"
    assert "score" in proposal["assessment"]
    assert (Path(result["run_path"]) / "neuron_candidate.json").exists()

    neuron = NeuronRegistry(db_path=tmp_path / "triade.db").get_neuron("lengua-negra")
    assert neuron is not None
    assert neuron["status"] in ("candidate", "candidate_reviewable", "experimental")


def test_conversation_intent_makes_no_proposal(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    result = runner.run("hola, ¿cómo estás?")

    assert result["neuron_proposal"] is None
    assert result["memory_diff"]["neuron_candidate_gate"]["route"] in {"ignore", "learning_candidate", "episodic_memory"}


def test_proposal_never_downgrades_a_promoted_neuron(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runner = make_runner(tmp_path)
    runner.run("crea neurona base", context={"active_neuron": "demo"})

    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE neurons SET status='experimental' WHERE name='demo'")

    result = runner.run("crea neurona demo otra vez", context={"active_neuron": "demo"})

    assert result["neuron_proposal"]["registered_as"] == "skipped_existing_promoted"
    assert NeuronRegistry(db_path=db_path).get_neuron("demo")["status"] == "experimental"


def test_propose_neurons_flag_disables_proposal(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    result = runner.run("crea algo", propose_neurons=False)

    assert result["neuron_proposal"] is None
    assert "neuron_proposal" in result["memory_diff"]

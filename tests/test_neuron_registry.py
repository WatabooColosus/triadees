"""Tests de registro persistente de neuronas 1.2C."""

from __future__ import annotations

from pathlib import Path

from triade.core.neuron_creator import NeuronCreator
from triade.core.neuron_registry import NeuronRegistry
from triade.core.neuron_trainer import NeuronTrainer


def test_neuron_registry_persists_neuron_and_training(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    creator = NeuronCreator()
    trainer = NeuronTrainer()
    registry = NeuronRegistry(db_path=db_path)

    spec = creator.create(
        name="Neurona Persistente",
        mission="Registrar una neurona interna en SQLite y validar su entrenamiento.",
        domain="core",
        rules=["Debe ser verificable.", "Debe conservar evidencia."],
    )
    result = trainer.evaluate(spec)

    neuron_id = registry.register(spec)
    training_id = registry.store_training(neuron_id, result)
    stored = registry.get_neuron("Neurona Persistente")
    training = registry.list_training(neuron_id)

    assert neuron_id > 0
    assert training_id > 0
    assert stored is not None
    assert stored["name"] == "Neurona Persistente"
    assert stored["status"] == result.status
    assert isinstance(stored["rules"], list)
    assert training
    assert training[0]["score"] == result.score


def test_neuron_registry_updates_existing_neuron(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    registry = NeuronRegistry(db_path=db_path)
    creator = NeuronCreator()

    spec_a = creator.create(
        name="Neurona Actualizable",
        mission="Primera misión suficientemente larga para crear la neurona.",
        domain="core",
    )
    spec_b = creator.create(
        name="Neurona Actualizable",
        mission="Segunda misión actualizada para confirmar upsert de la neurona.",
        domain="updated-core",
    )

    first_id = registry.register(spec_a)
    second_id = registry.register(spec_b)
    stored = registry.get_neuron("Neurona Actualizable")

    assert first_id == second_id
    assert stored is not None
    assert stored["domain"] == "updated-core"
    assert "Segunda misión" in stored["mission"]


def test_neuron_registry_lists_recent_neurons(tmp_path: Path) -> None:
    registry = NeuronRegistry(db_path=tmp_path / "triade.db")
    creator = NeuronCreator()

    for index in range(3):
        spec = creator.create(
            name=f"Neurona Lista {index}",
            mission=f"Misión verificable de prueba número {index} para listado interno.",
            domain="list-test",
        )
        registry.register(spec)

    neurons = registry.list_neurons(limit=2)

    assert len(neurons) == 2
    assert all("Neurona Lista" in item["name"] for item in neurons)

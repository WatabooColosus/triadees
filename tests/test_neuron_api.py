from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apps.api_app import app
from triade.core.neuron_creator import NeuronCreator, NeuronSpec
from triade.core.neuron_registry import NeuronRegistry
from triade.core.neuron_trainer import NeuronTrainer


client = TestClient(app)


def seed_neuron(db_path: str, name: str = "Neurona API") -> int:
    creator = NeuronCreator()
    trainer = NeuronTrainer()
    registry = NeuronRegistry(db_path=db_path)
    spec = creator.create(
        name=name,
        mission="Crear una neurona para validar gestion interna.",
        domain="api-test",
        rules=["Debe ser verificable.", "Debe responder por HTTP."],
    )
    neuron_id = registry.register(spec)
    result = trainer.evaluate(spec)
    registry.store_training(neuron_id, result)
    return neuron_id


def test_neuron_api_list_show(tmp_path: Path) -> None:
    db_path = str(tmp_path / "triade.db")
    seed_neuron(db_path)

    listed = client.get("/triade/neurons", params={"db_path": db_path, "limit": 5})
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert listed_payload["status"] == "ok"
    assert any(item["name"] == "Neurona API" for item in listed_payload["neurons"])

    shown = client.get("/triade/neurons/Neurona API", params={"db_path": db_path})
    assert shown.status_code == 200
    shown_payload = shown.json()
    assert shown_payload["neuron"]["name"] == "Neurona API"
    assert shown_payload["training"]


def test_neuron_api_show_not_found(tmp_path: Path) -> None:
    db_path = str(tmp_path / "triade.db")

    response = client.get("/triade/neurons/No Existe", params={"db_path": db_path})

    assert response.status_code == 404

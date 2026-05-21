"""Tests de API neuronal 1.2E."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apps.api_app import app


client = TestClient(app)


def test_neuron_api_create_list_show(tmp_path: Path) -> None:
    db_path = str(tmp_path / "triade.db")

    created = client.post(
        "/triade/neurons",
        json={
            "name": "Neurona API",
            "mission": "Crear una neurona desde FastAPI para validar gestion interna.",
            "domain": "api-test",
            "rules": ["Debe ser verificable.", "Debe responder por HTTP."],
            "db_path": db_path,
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["status"] == "ok"
    assert payload["neuron_id"] > 0
    assert payload["training"]["status"] in {"experimental", "stable"}

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

from pathlib import Path

from fastapi.testclient import TestClient

from apps.routes import api as routes_api
from apps.single_port_app import app
from triade.qualia.bus import QualiaBus
from triade.qualia.store import QualiaStore


def test_qualia_api_endpoints_use_real_store(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "triade.db"

    class StoreFactory:
        def __call__(self, *args, **kwargs):
            return QualiaStore(db_path=db)

    class BusFactory:
        def __call__(self, *args, **kwargs):
            return QualiaBus(db_path=db)

    monkeypatch.setattr(routes_api, "QualiaStore", StoreFactory())
    monkeypatch.setattr(routes_api, "QualiaBus", BusFactory())
    client = TestClient(app)
    response = client.post("/qualia/publish-test", json={"run_id": "run-api", "proposed_learning": "Aprender vía API Qualia."})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert client.get("/qualia/experiences", params={"run_id": "run-api"}).json()["count"] == 1
    assert client.get("/qualia/signals", params={"run_id": "run-api"}).json()["count"] == 1
    assert client.get("/qualia/central-packets", params={"run_id": "run-api"}).json()["count"] == 1
    assert client.get("/qualia/storage-packets", params={"run_id": "run-api"}).json()["count"] == 1
    assert client.get("/qualia/state", params={"run_id": "run-api"}).json()["latest_state"]["run_id"] == "run-api"


def test_qualia_api_state_empty(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "triade.db"

    class StoreFactory:
        def __call__(self, *args, **kwargs):
            return QualiaStore(db_path=db)

    monkeypatch.setattr(routes_api, "QualiaStore", StoreFactory())
    client = TestClient(app)
    resp = client.get("/qualia/state", params={"run_id": "nonexistent"})
    assert resp.status_code == 200
    assert resp.json()["latest_state"] is None


def test_qualia_api_publish_test_without_learning(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "triade.db"

    class StoreFactory:
        def __call__(self, *args, **kwargs):
            return QualiaStore(db_path=db)

    class BusFactory:
        def __call__(self, *args, **kwargs):
            return QualiaBus(db_path=db)

    monkeypatch.setattr(routes_api, "QualiaStore", StoreFactory())
    monkeypatch.setattr(routes_api, "QualiaBus", BusFactory())
    client = TestClient(app)
    resp = client.post("/qualia/publish-test", json={"run_id": "run-nl"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

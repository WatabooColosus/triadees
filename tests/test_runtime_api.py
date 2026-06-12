from __future__ import annotations

from fastapi.testclient import TestClient

from apps.single_port_app import app
import apps.routes.api as api_module
from triade.core.context_engine import build_living_context_for_chat
from triade.core.internal_runtime import InternalRuntimeSupervisor
from triade.core.living_report import build_living_report


def test_runtime_api_endpoints(monkeypatch, tmp_path):
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    supervisor = InternalRuntimeSupervisor(db_path=db_path, runs_dir=runs_dir)

    monkeypatch.setattr(api_module, "get_internal_runtime_supervisor", lambda **_: supervisor)
    monkeypatch.setattr(api_module, "get_internal_runtime_state", lambda **_: supervisor.snapshot())
    monkeypatch.setattr(api_module, "build_internal_context_snapshot", lambda **kwargs: {"status": "ok", "runtime": supervisor.snapshot()})
    monkeypatch.setattr(api_module, "start_internal_runtime_background", lambda **kwargs: {"status": "started", "snapshot": supervisor.snapshot()})
    monkeypatch.setattr(api_module, "stop_internal_runtime_background", lambda **kwargs: {"status": "stop_requested", "snapshot": supervisor.snapshot()})
    monkeypatch.setattr(api_module, "build_living_context_for_chat", lambda user_input="", limit=10: build_living_context_for_chat(user_input, db_path=db_path, runs_dir=runs_dir, limit=limit))
    monkeypatch.setattr(api_module, "build_living_report", lambda limit=20: build_living_report(db_path=db_path, runs_dir=runs_dir, limit=limit))
    monkeypatch.setattr(api_module, "list_recent_events", lambda limit=50: [])
    monkeypatch.setattr(api_module, "audit_stable_neurons", lambda **kwargs: {"status": "ok", "mode": "stable_neuron_audit", "total_stable_neurons": 0, "stable_with_enough_evidence": 0, "stable_needs_review": 0, "neurons": [], "policy": {"read_only_by_default": True}})
    monkeypatch.setattr(api_module, "apply_stable_neuron_audit", lambda **kwargs: {"status": "ok", "mode": "stable_neuron_audit", "applied": True, "applied_count": 0, "applied_changes": []})

    client = TestClient(app)

    assert client.get("/api/runtime/status").status_code == 200
    assert client.post("/api/runtime/once", json={"mode": "observe_only"}).status_code == 200
    assert client.get("/api/runtime/events").status_code == 200
    assert client.get("/api/runtime/context", params={"user_input": "estado runtime"}).status_code == 200
    assert client.get("/api/system/living-context", params={"user_input": "estado runtime"}).status_code == 200
    assert client.get("/api/system/living-report").status_code == 200
    assert client.get("/api/neurons/stable-audit").status_code == 200
    assert client.post("/api/neurons/stable-audit/apply").status_code == 200

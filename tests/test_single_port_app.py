"""Tests de Tríade Single Port App."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps import single_port_app
from apps.single_port_app import app, federated_model_plan


client = TestClient(app)


def test_single_port_ui_serves_html() -> None:
    response = client.get("/ui")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Tríade Ω Single Port" in response.text
    assert "/api/run" in response.text
    assert "/api/router/doctor" in response.text
    assert "Pulso vivo" in response.text
    assert "Herramientas ocasionales" in response.text
    assert "/downloads/triade-android-node.apk" in response.text
    assert "/api/system/model-capacity" in response.text


def test_single_port_health() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["mode"] == "single-port"
    assert payload["port"] == 8010
    assert "hardware" in payload
    assert "doctor" in payload


def test_single_port_router_doctor() -> None:
    response = client.post("/api/router/doctor", json={"intent": "analyze", "urgency": "medium"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["mode"] == "single-port"
    assert "hardware" in payload
    assert "router" in payload
    assert "decisions" in payload["router"]


def test_single_port_model_compatibility() -> None:
    response = client.get("/api/models/compatibility")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["mode"] == "single-port"
    assert "matrix" in payload
    assert "models" in payload["matrix"]
    assert "counts" in payload["matrix"]


def test_single_port_model_install_queue() -> None:
    response = client.get("/api/models/install-queue")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["mode"] == "install-queue"
    assert "policy" in payload
    assert payload["policy"]["auto_install"] is False
    assert "candidates" in payload


def test_single_port_model_capacity() -> None:
    response = client.get("/api/system/model-capacity")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["mode"] == "model-capacity"
    assert "local" in payload
    assert "federation" in payload
    assert "missing_for_comfortable_models" in payload["local"]
    assert "nodes" in payload["federation"]
    assert "authorized" in payload["federation"]
    assert "observers" not in payload["federation"]
    assert "constants" in payload


def test_federated_model_plan_sums_authorized_resources() -> None:
    plan = federated_model_plan(
        [
            {
                "can_feed_local_models": True,
                "federation_complete": True,
                "cpu_authorized_count": 4,
                "ram_authorized_gb": 2.1,
                "ram_available_gb": 2.5,
                "capabilities": {},
            },
            {
                "can_feed_local_models": True,
                "federation_complete": True,
                "cpu_authorized_count": 4,
                "ram_authorized_gb": 2.2,
                "ram_available_gb": 2.6,
                "capabilities": {},
            },
        ]
    )

    assert plan["cpu_authorized_count"] == 8
    assert plan["ram_authorized_gb"] == 4.3
    assert any(item["model"] == "qwen2.5:3b-instruct" for item in plan["runnable_by_aggregate_ram"])
    assert plan["can_run_single_llm_by_sum"] is False
    assert plan["runtime"] == "pending_distributed_inference_runtime"


def test_single_port_serves_android_apk() -> None:
    response = client.get("/downloads/triade-android-node.apk")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.android.package-archive"
    assert int(response.headers["content-length"]) > 30000


def test_single_port_accepts_local_android_node_heartbeat(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(single_port_app, "local_node_token_path", lambda: tmp_path / "local_node_tokens.json")

    def fake_upsert(node_id: str, name: str, capabilities: dict):
        return {"node_id": node_id, "name": name, "capabilities": single_port_app.local_node_capabilities(node_id, capabilities)}

    monkeypatch.setattr(single_port_app, "upsert_local_android_node", fake_upsert)

    register = client.post(
        "/api/register",
        json={
            "display_name": "Android local",
            "capabilities": {
                "native_android": True,
                "app_node": True,
                "cpu_count": 8,
                "ram_available_gb": 2.0,
                "resource_limit_percent": 90,
                "cpu_authorized_count": 7,
                "ram_authorized_gb": 1.8,
            },
        },
    )

    assert register.status_code == 200
    identity = register.json()
    heartbeat = client.post(
        "/api/heartbeat",
        json={
            "node_id": identity["node_id"],
            "node_token": identity["node_token"],
            "capabilities": {
                "native_android": True,
                "app_node": True,
                "cpu_count": 8,
                "ram_available_gb": 2.0,
                "resource_limit_percent": 90,
                "cpu_authorized_count": 7,
                "ram_authorized_gb": 1.8,
            },
        },
    )

    assert heartbeat.status_code == 200
    caps = heartbeat.json()["node"]["capabilities"]
    assert caps["resource_limit_percent"] == 90
    assert caps["cpu_authorized_count"] == 7
    assert caps["ram_authorized_gb"] == 1.8


def test_single_port_local_job_cycle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(single_port_app, "local_node_token_path", lambda: tmp_path / "local_node_tokens.json")
    single_port_app.LOCAL_JOBS.clear()
    node_id = "local-test-node"
    job = single_port_app.create_local_job(node_id, "browser_benchmark", seconds=1)

    next_job = client.get("/api/jobs/next", params={"node_id": node_id})

    assert next_job.status_code == 200
    payload = next_job.json()
    assert payload["status"] == "ok"
    assert payload["job"]["job_id"] == job["job_id"]

    result = client.post(
        f"/api/jobs/{job['job_id']}/result",
        json={
            "node_id": node_id,
            "status": "completed",
            "result": {"task": "browser_benchmark", "seconds": 1, "score": 12345},
        },
    )

    assert result.status_code == 200
    assert single_port_app.LOCAL_JOBS[job["job_id"]]["status"] == "completed"
    assert single_port_app.LOCAL_JOBS[job["job_id"]]["result"]["score"] == 12345


def test_distributed_runtime_preprocess_merges_android_results(monkeypatch) -> None:
    single_port_app.LOCAL_JOBS.clear()
    monkeypatch.setattr(
        single_port_app,
        "local_federated_nodes",
        lambda task=None: [
            {"node_id": "android-a", "capabilities": {"allowed_tasks": ["preprocess_text"]}},
            {"node_id": "android-b", "capabilities": {"allowed_tasks": ["preprocess_text"]}},
        ],
    )

    def fake_wait(job_id: str, timeout: float = 25.0, interval: float = 0.5):
        job = single_port_app.LOCAL_JOBS[job_id]
        return {
            **job,
            "status": "completed",
            "result": {
                "task": "preprocess_text",
                "chars": len(job["payload"]["text"]),
                "word_count": 2,
                "approx_tokens": 3,
                "keywords": [{"term": "triade", "count": 1}],
                "chunks": [{"index": 0, "text": job["payload"]["text"]}],
            },
        }

    monkeypatch.setattr(single_port_app, "wait_local_job", fake_wait)
    response = client.post(
        "/api/distributed-runtime/preprocess",
        json={"text": "triade federada alimenta modelo local con contexto distribuido", "wait_timeout": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["submitted"] == 2
    assert payload["completed"] == 2
    assert payload["model_feed"]["ready_for_local_model"] is True
    assert payload["model_feed"]["keywords"][0]["term"] == "triade"


def test_distributed_runtime_probe_reports_remote_ops(monkeypatch) -> None:
    single_port_app.LOCAL_JOBS.clear()
    monkeypatch.setattr(
        single_port_app,
        "local_federated_nodes",
        lambda task=None: [{"node_id": "android-a", "capabilities": {"allowed_tasks": ["federated_inference_probe"]}}],
    )

    def fake_wait(job_id: str, timeout: float = 25.0, interval: float = 0.5):
        job = single_port_app.LOCAL_JOBS[job_id]
        return {
            **job,
            "status": "completed",
            "result": {
                "task": "federated_inference_probe",
                "status": "completed",
                "ops": job["payload"]["iterations"],
                "prompt_sha256": "abc123",
            },
        }

    monkeypatch.setattr(single_port_app, "wait_local_job", fake_wait)
    response = client.post(
        "/api/distributed-runtime/probe",
        json={"prompt": "prueba runtime", "iterations": 5000, "wait_timeout": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["completed"] == 1
    assert payload["total_ops"] == 5000
    assert "tensor-paralela" in payload["truth"]


def test_single_port_run_accepts_auto_select_models() -> None:
    response = client.post(
        "/api/run",
        json={
            "text": "Prueba auto selección desde single port",
            "use_ollama": False,
            "hypothalamus_model": "",
            "central_model": "",
            "auto_select_models": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"]
    assert "model_selection" in payload

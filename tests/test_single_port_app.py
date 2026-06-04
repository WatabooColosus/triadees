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


def test_federation_resource_lease_tracks_transports_and_resources() -> None:
    lease = single_port_app.federation_resource_lease(
        [
            {
                "node_id": "local-android",
                "name": "Android LAN",
                "online": True,
                "can_feed_local_models": True,
                "federation_complete": True,
                "cpu_authorized_count": 8,
                "ram_authorized_gb": 3.3,
                "ram_available_gb": 3.3,
                "resource_limit_percent": 100,
                "resource_limit_reported": True,
                "edge_model_runtime": True,
                "model_runtime_backend": "none",
                "can_host_llm": False,
                "capabilities": {
                    "relay_url": "http://192.168.1.12:8010",
                    "allowed_tasks": ["preprocess_text", "android_model_doctor"],
                    "app_version": "0.5.0",
                    "large_memory_class_mb": 1024,
                },
            },
            {
                "node_id": "relay-android",
                "name": "Android Relay",
                "online": True,
                "can_feed_local_models": True,
                "federation_complete": True,
                "cpu_authorized_count": 4,
                "ram_authorized_gb": 2.0,
                "ram_available_gb": 2.0,
                "resource_limit_percent": 100,
                "resource_limit_reported": False,
                "edge_model_runtime": False,
                "model_runtime_backend": "none",
                "can_host_llm": False,
                "capabilities": {"relay_url": "https://relay.test", "allowed_tasks": ["preprocess_text"]},
            },
        ]
    )

    assert lease["totals"]["devices"] == 2
    assert lease["totals"]["direct_lan_devices"] == 1
    assert lease["totals"]["relay_devices"] == 1
    assert lease["totals"]["cpu_authorized_count"] == 12
    assert lease["totals"]["ram_authorized_gb"] == 5.3
    assert lease["leases"][0]["resource_limit_percent"] == 100
    assert lease["leases"][0]["lease_status"] == "job_worker_ready"


def test_single_port_serves_android_apk() -> None:
    response = client.get("/downloads/triade-android-node.apk")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.android.package-archive"
    assert int(response.headers["content-length"]) > 20000


def test_single_port_android_runtime_manifest_reports_missing_assets(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(single_port_app, "ANDROID_LLAMA_CLI_PATH", tmp_path / "missing-llama-cli")
    monkeypatch.setattr(single_port_app, "ANDROID_BASE_MODEL_PATH", tmp_path / "missing-model.gguf")

    response = client.get("/downloads/android/runtime-manifest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "incomplete"
    assert payload["llama_cli"]["ready"] is False
    assert payload["base_model"]["ready"] is False


def test_single_port_serves_android_runtime_assets(tmp_path, monkeypatch) -> None:
    llama = tmp_path / "llama-cli"
    model = tmp_path / "triade-base.gguf"
    llama.write_bytes(b"llama-bin")
    model.write_bytes(b"gguf-model")
    monkeypatch.setattr(single_port_app, "ANDROID_LLAMA_CLI_PATH", llama)
    monkeypatch.setattr(single_port_app, "ANDROID_BASE_MODEL_PATH", model)

    manifest = client.get("/downloads/android/runtime-manifest")
    llama_response = client.get("/downloads/android/llama-cli")
    model_response = client.get("/downloads/android/base-model.gguf")
    script_response = client.get("/downloads/android/termux-bootstrap.sh")

    assert manifest.json()["status"] == "ok"
    assert llama_response.status_code == 200
    assert llama_response.content == b"llama-bin"
    assert model_response.status_code == 200
    assert model_response.content == b"gguf-model"
    assert script_response.status_code == 200
    assert "pkg install" in script_response.text


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
                "resource_limit_percent": 100,
                "cpu_authorized_count": 8,
                "ram_authorized_gb": 2.0,
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
                "resource_limit_percent": 100,
                "cpu_authorized_count": 8,
                "ram_authorized_gb": 2.0,
            },
        },
    )

    assert heartbeat.status_code == 200
    caps = heartbeat.json()["node"]["capabilities"]
    assert caps["resource_limit_percent"] == 100
    assert caps["cpu_authorized_count"] == 8
    assert caps["ram_authorized_gb"] == 2.0


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


def test_distributed_runtime_preprocess_falls_back_to_public_relay(monkeypatch) -> None:
    monkeypatch.setattr(single_port_app, "local_federated_nodes", lambda task=None: [])
    monkeypatch.setattr(single_port_app, "relay_settings", lambda: {"url": "https://relay.test", "admin_token": "token"})

    class FakeRelayClient:
        def __init__(self, url: str, admin_token: str, timeout: float = 12.0) -> None:
            self.url = url
            self.admin_token = admin_token

        def preprocess_text_online(self, federation, text: str, max_chunk_chars: int = 1200, wait_timeout: float = 45.0):
            return {
                "status": "ok",
                "submitted": 1,
                "completed": 1,
                "results": [{"node_id": "relay-android", "job": {"status": "completed"}}],
                "model_feed": {"ready_for_local_model": True, "keywords": [{"term": "relay", "count": 1}]},
            }

    monkeypatch.setattr(single_port_app, "PublicRelayClient", FakeRelayClient)
    response = client.post(
        "/api/distributed-runtime/preprocess",
        json={"text": "relay alimenta triade", "wait_timeout": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["transport"] == "public_relay_fallback"
    assert payload["completed"] == 1
    assert payload["model_feed"]["ready_for_local_model"] is True


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


def test_distributed_runtime_android_model_doctor_reports_unavailable_backend(monkeypatch) -> None:
    monkeypatch.setattr(
        single_port_app,
        "local_federated_nodes",
        lambda task=None: [{"node_id": "android-a", "capabilities": {"allowed_tasks": ["android_model_doctor"]}}],
    )

    def fake_wait(job_id: str, timeout: float = 25.0, interval: float = 0.5):
        job = single_port_app.LOCAL_JOBS[job_id]
        return {
            **job,
            "status": "completed",
            "result": {
                "task": "android_model_doctor",
                "backend": "none",
                "native_backend_present": False,
                "can_run_local_llm": False,
            },
        }

    monkeypatch.setattr(single_port_app, "wait_local_job", fake_wait)
    response = client.post("/api/distributed-runtime/android-model-doctor", json={"wait_timeout": 1})

    assert response.status_code == 200
    payload = response.json()
    assert payload["transport"] == "lan_8010"
    assert payload["completed"] == 1
    assert payload["can_host_llm_count"] == 0
    assert payload["doctors"][0]["backend"] == "none"


def test_android_local_generate_requires_real_llm_host(monkeypatch) -> None:
    monkeypatch.setattr(single_port_app, "local_federated_nodes", lambda task=None: [])
    monkeypatch.setattr(single_port_app, "relay_settings", lambda: {"url": "https://relay.test", "admin_token": None})

    response = client.post(
        "/api/distributed-runtime/android-local-generate",
        json={"prompt": "hola desde android", "wait_timeout": 5},
    )

    assert response.status_code == 404
    assert "No hay host LLM Android real" in response.json()["detail"]


def test_android_local_generate_uses_ready_local_host(monkeypatch) -> None:
    single_port_app.LOCAL_JOBS.clear()
    monkeypatch.setattr(
        single_port_app,
        "local_federated_nodes",
        lambda task=None: [
            {
                "node_id": "android-llm",
                "capabilities": {
                    "allowed_tasks": ["android_local_generate"],
                    "can_run_local_llm": True,
                    "local_model_runtime_ready": True,
                    "model_support": {"can_host_llm": True},
                },
            }
        ],
    )

    def fake_wait(job_id: str, timeout: float = 25.0, interval: float = 0.5):
        job = single_port_app.LOCAL_JOBS[job_id]
        return {
            **job,
            "status": "completed",
            "result": {
                "task": "android_local_generate",
                "ok": True,
                "status": "completed",
                "backend": "llama.cpp",
                "model": "tiny.gguf",
                "response": "respuesta android",
                "threads": 4,
            },
        }

    monkeypatch.setattr(single_port_app, "wait_local_job", fake_wait)
    response = client.post(
        "/api/distributed-runtime/android-local-generate",
        json={"prompt": "hola desde android", "model": "tiny.gguf", "max_tokens": 16, "wait_timeout": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["transport"] == "lan_8010"
    assert payload["response"] == "respuesta android"
    assert single_port_app.LOCAL_JOBS[payload["job"]["job_id"]]["payload"]["model"] == "tiny.gguf"


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

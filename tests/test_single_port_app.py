"""Tests de Tríade Single Port App."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from apps import services, single_port_app
from apps.routes import api as routes_api
from apps.single_port_app import app, federated_model_plan
from triade.federation.contracts import sign_payload


client = TestClient(app)


def test_single_port_ui_serves_html() -> None:
    response = client.get("/ui")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>Tríade Ω</title>" in response.text or "Tríade Ω · Consola limpia" in response.text
    assert "root" in response.text or "Tríade Ω · Consola limpia" in response.text
    assert "Tríade" in response.text


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


def test_single_port_system_pulse_summarizes_alerts() -> None:
    response = client.get("/api/system/pulse", params={"sync_relay": "false"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "system-pulse"
    assert payload["level"] in {"ok", "warn", "bad"}
    assert "alerts" in payload
    assert "checks" in payload
    assert "life" in payload
    assert "qualia" in payload
    assert "capacity" in payload
    assert payload["life"]["mode"] == "life-pulse"
    assert payload["qualia"]["mode"] == "qualia"
    names = {item["name"] for item in payload["checks"]}
    assert {"router", "semantic_memory", "signed_transport", "model_queue"}.issubset(names)


def test_single_port_life_endpoint_reports_background_counters() -> None:
    response = client.get("/api/system/life", params={"tick": "true"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "life-pulse"
    assert payload["policy"]["background_learning"] == "candidate_detection_only"
    assert payload["policy"]["auto_consolidation"] is False
    assert "counters" in payload
    assert "integrity" in payload
    assert "reflection" in payload


def test_continuous_runner_control_endpoint_default_safe() -> None:
    response = client.post(
        "/api/system/life/continuous-runner",
        json={"enabled": False, "autonomy_level": "observe_only", "interval_seconds": 1, "max_cycles": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["continuous_runner"]["enabled"] is False
    assert payload["continuous_runner"]["interval_seconds"] >= 10
    assert payload["policy"]["default_remains_off"] is True


def test_continuous_runner_control_rejects_invalid_autonomy_level() -> None:
    response = client.post(
        "/api/system/life/continuous-runner",
        json={"enabled": False, "autonomy_level": "invalid"},
    )

    assert response.status_code == 400


def test_full_neuron_operational_state_endpoint() -> None:
    response = client.get("/api/system/neurons/full", params={"limit": 5, "mission_limit": 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "full_neuron_operational_state"
    assert "neurons" in payload
    assert "missions" in payload
    assert "learning_usage" in payload
    assert payload["policy"]["read_only"] is True
    assert payload["policy"]["identity_core_protected"] is True


def test_single_port_qualia_endpoint_aligns_semantic_memory_and_pulse() -> None:
    response = client.get("/api/system/qualia", params={"refresh_life": "true"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "qualia"
    assert payload["semantic_alignment"]["alignment"] == "aligned_with_life_pulse"
    assert payload["senses"]["mode"] == "internal_senses"
    assert "Pulso vivo" in {item["name"] for item in payload["organs"]}
    assert "sentidos internos" in payload["semantic_alignment"]["live_state_relation"]
    assert payload["morphological_crystal"]["status"] in {"ok", "empty"}
    assert payload["qualia_crystal_connection"]["flow"] == [
        "qualia_bus",
        "hypothalamus_modulation",
        "crystal_regulation",
        "central_plan",
    ]


def test_public_guarded_mode_blocks_admin_writes_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("TRIADE_API_KEY", raising=False)
    monkeypatch.setenv("TRIADE_PUBLIC_GUARDED", "1")

    response = client.post("/api/runtime/stop")

    assert response.status_code == 403
    assert response.json()["public_guarded"] is True


def test_single_port_chat_sees_operational_awareness_from_life_pulse() -> None:
    response = client.post(
        "/api/run",
        json={
            "text": "Que neuronas propuestas ves en tu pulso vivo y cuanta RAM tienes?",
            "source": "test",
            "use_ollama": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    text = payload["response"].lower()
    assert "pulso vivo" in text
    assert "qualia" in text
    assert "soy tríade" in text or "soy triade" in text
    assert "arquitectura viva" in text
    assert "central ordena" in text
    assert "sentidos internos" in text
    assert "señales de necesidad interna" in text or "senales de necesidad interna" in text
    assert "bodega semántica" in text or "bodega semantica" in text
    assert "memoria semántica" in text or "memoria semantica" in text
    assert "ram libre local" in text


def test_single_port_chat_answers_semantic_memory_state_with_qualia() -> None:
    response = client.post(
        "/api/run",
        json={
            "text": "Tu memoria semántica es real y continua?",
            "source": "test",
            "use_ollama": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    text = payload["response"].lower()
    assert "bodega semántica" in text or "bodega semantica" in text
    assert "qualia" in text
    assert "memoria semántica" in text or "memoria semantica" in text
    assert payload["memory_diff"]["semantic_continuity"]["status"] == "ok"
    assert payload["memory_diff"]["semantic_continuity"]["embedding_event"]["ok"] is True


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


def test_single_port_android_apk_missing_until_artifact_is_copied(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(services, "ANDROID_APK_PATH", tmp_path / "missing.apk")

    response = client.get("/downloads/triade-android-node.apk")

    assert response.status_code == 404


def test_single_port_serves_android_apk_when_artifact_exists(tmp_path, monkeypatch) -> None:
    apk = tmp_path / "triade-android-node.apk"
    apk.write_bytes(b"PK\x03\x04" + b"apk" * 1024)
    monkeypatch.setattr(services, "ANDROID_APK_PATH", apk)

    response = client.get("/downloads/triade-android-node.apk")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.android.package-archive"
    assert int(response.headers["content-length"]) == apk.stat().st_size


def test_single_port_android_runtime_manifest_reports_missing_assets(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(services, "ANDROID_LLAMA_CLI_PATH", tmp_path / "missing-llama-cli")
    monkeypatch.setattr(services, "ANDROID_BASE_MODEL_PATH", tmp_path / "missing-model.gguf")

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
    monkeypatch.setattr(services, "ANDROID_LLAMA_CLI_PATH", llama)
    monkeypatch.setattr(services, "ANDROID_BASE_MODEL_PATH", model)

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
    monkeypatch.setattr(services, "local_node_token_path", lambda: tmp_path / "local_node_tokens.json")

    def fake_upsert(node_id: str, name: str, capabilities: dict):
        return {"node_id": node_id, "name": name, "capabilities": services.local_node_capabilities(node_id, capabilities)}

    monkeypatch.setattr(services, "upsert_local_android_node", fake_upsert)

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
    monkeypatch.setattr(services, "local_node_token_path", lambda: tmp_path / "local_node_tokens.json")
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


def test_signed_federated_transport_local_job_cycle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(services, "local_node_token_path", lambda: tmp_path / "local_node_tokens.json")
    single_port_app.LOCAL_JOBS.clear()
    register = client.post("/api/register", json={"display_name": "Android firmado", "capabilities": {"native_android": True, "app_node": True}})
    identity = register.json()
    job = single_port_app.create_local_job(identity["node_id"], "sha256", payload={"hello": "triade"})

    next_payload = {"request": "next_job"}
    timestamp = int(time.time())
    next_envelope = {
        "node_id": identity["node_id"],
        "timestamp": timestamp,
        "nonce": "nonce-next-12345",
        "payload": next_payload,
        "signature": sign_payload(identity["node_token"], identity["node_id"], timestamp, "nonce-next-12345", next_payload),
        "public_key": "android-test-key",
    }
    next_job = client.post("/api/federation/transport/next", json=next_envelope)

    assert next_job.status_code == 200
    assert next_job.json()["job"]["job_id"] == job["job_id"]
    assert single_port_app.LOCAL_JOBS[job["job_id"]]["status"] == "running"

    result_payload = {"job_id": job["job_id"], "status": "completed", "result": {"sha256": "abc"}, "error": None}
    result_timestamp = int(time.time())
    result_envelope = {
        "node_id": identity["node_id"],
        "timestamp": result_timestamp,
        "nonce": "nonce-result-123",
        "payload": result_payload,
        "signature": sign_payload(identity["node_token"], identity["node_id"], result_timestamp, "nonce-result-123", result_payload),
        "public_key": "android-test-key",
    }
    result = client.post("/api/federation/transport/result", json=result_envelope)

    assert result.status_code == 200
    assert single_port_app.LOCAL_JOBS[job["job_id"]]["status"] == "completed"
    assert single_port_app.LOCAL_JOBS[job["job_id"]]["result"]["sha256"] == "abc"


def test_signed_federated_transport_rejects_bad_signature(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(services, "local_node_token_path", lambda: tmp_path / "local_node_tokens.json")
    single_port_app.LOCAL_JOBS.clear()
    register = client.post("/api/register", json={"display_name": "Android firmado", "capabilities": {"native_android": True, "app_node": True}})
    identity = register.json()
    single_port_app.create_local_job(identity["node_id"], "sha256", payload={"hello": "triade"})

    response = client.post(
        "/api/federation/transport/next",
        json={
            "node_id": identity["node_id"],
            "timestamp": int(time.time()),
            "nonce": "nonce-bad-12345",
            "payload": {"request": "next_job"},
            "signature": "0" * 64,
        },
    )

    assert response.status_code == 401


def test_signed_federated_transport_rejects_replayed_nonce(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(services, "local_node_token_path", lambda: tmp_path / "local_node_tokens.json")
    routes_api.SIGNED_NONCE_CACHE.clear()
    single_port_app.LOCAL_JOBS.clear()
    register = client.post("/api/register", json={"display_name": "Android firmado", "capabilities": {"native_android": True, "app_node": True}})
    identity = register.json()
    single_port_app.create_local_job(identity["node_id"], "sha256", payload={"hello": "triade"})

    payload = {"request": "next_job"}
    timestamp = int(time.time())
    envelope = {
        "node_id": identity["node_id"],
        "timestamp": timestamp,
        "nonce": "nonce-replay-12345",
        "payload": payload,
        "signature": sign_payload(identity["node_token"], identity["node_id"], timestamp, "nonce-replay-12345", payload),
    }

    first = client.post("/api/federation/transport/next", json=envelope)
    replay = client.post("/api/federation/transport/next", json=envelope)

    assert first.status_code == 200
    assert replay.status_code == 409
    assert "replay" in replay.json()["detail"].lower()


def test_signed_nonce_cache_prunes_expired_entries() -> None:
    routes_api.SIGNED_NONCE_CACHE.clear()
    routes_api.SIGNED_NONCE_CACHE["node:old"] = 1.0

    routes_api._prune_signed_nonce_cache(now=2.0)

    assert routes_api.SIGNED_NONCE_CACHE == {}


def test_local_jobs_only_accept_sandbox_tasks() -> None:
    try:
        single_port_app.create_local_job("node", "execute_system_commands")
    except ValueError as exc:
        assert "sandbox federado" in str(exc)
    else:
        raise AssertionError("create_local_job accepted a task outside the federation sandbox")


def test_distributed_runtime_preprocess_merges_android_results(monkeypatch) -> None:
    single_port_app.LOCAL_JOBS.clear()
    fake_nodes = lambda task=None: [
        {"node_id": "android-a", "capabilities": {"allowed_tasks": ["preprocess_text"]}},
        {"node_id": "android-b", "capabilities": {"allowed_tasks": ["preprocess_text"]}},
    ]
    monkeypatch.setattr(single_port_app, "local_federated_nodes", fake_nodes)
    monkeypatch.setattr(routes_api, "local_federated_nodes", fake_nodes)

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

    monkeypatch.setattr(routes_api, "wait_local_job", fake_wait)
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
    monkeypatch.setattr(routes_api, "local_federated_nodes", lambda task=None: [])
    monkeypatch.setattr(routes_api, "relay_settings", lambda: {"url": "https://relay.test", "admin_token": "token"})

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

    monkeypatch.setattr(routes_api, "PublicRelayClient", FakeRelayClient)
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
        routes_api,
        "local_federated_nodes",
        lambda task=None: [{"node_id": "android-a", "capabilities": {"allowed_tasks": ["federated_inference_probe"]}}],
    )

    def fake_wait(job_id: str, timeout: float = 25.0, interval: float = 0.5):
        job = services.LOCAL_JOBS[job_id]
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

    monkeypatch.setattr(routes_api, "wait_local_job", fake_wait)
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
        routes_api,
        "local_federated_nodes",
        lambda task=None: [{"node_id": "android-a", "capabilities": {"allowed_tasks": ["android_model_doctor"]}}],
    )

    def fake_wait(job_id: str, timeout: float = 25.0, interval: float = 0.5):
        job = services.LOCAL_JOBS[job_id]
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

    monkeypatch.setattr(routes_api, "wait_local_job", fake_wait)
    response = client.post("/api/distributed-runtime/android-model-doctor", json={"wait_timeout": 1})

    assert response.status_code == 200
    payload = response.json()
    assert payload["transport"] == "lan_8010"
    assert payload["completed"] == 1
    assert payload["can_host_llm_count"] == 0
    assert payload["doctors"][0]["backend"] == "none"


def test_android_local_generate_requires_real_llm_host(monkeypatch) -> None:
    monkeypatch.setattr(routes_api, "local_federated_nodes", lambda task=None: [])
    monkeypatch.setattr(routes_api, "relay_settings", lambda: {"url": "https://relay.test", "admin_token": None})

    response = client.post(
        "/api/distributed-runtime/android-local-generate",
        json={"prompt": "hola desde android", "wait_timeout": 5},
    )

    assert response.status_code == 404
    assert "No hay host LLM Android real" in response.json()["detail"]


def test_android_local_generate_uses_ready_local_host(monkeypatch) -> None:
    single_port_app.LOCAL_JOBS.clear()
    monkeypatch.setattr(
        routes_api,
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
        job = services.LOCAL_JOBS[job_id]
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

    monkeypatch.setattr(routes_api, "wait_local_job", fake_wait)
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

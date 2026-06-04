from __future__ import annotations

import httpx

from triade.federation.federation import Federation
from triade.federation.relay_client import PublicRelayClient


def make_client(handler):
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport, base_url="https://relay.test")


def test_sync_nodes_to_federation(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer admin"
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "nodes": [
                    {
                        "node_id": "web-phone",
                        "display_name": "Celular",
                        "online": True,
                        "capabilities": {
                            "tier": "browser",
                            "cpu_count": 8,
                            "device_memory_gb": 8,
                            "platform": "Android",
                        },
                    }
                ],
            },
        )

    federation = Federation(db_path=tmp_path / "triade.db")
    client = PublicRelayClient("https://relay.test", "admin", client=make_client(handler))

    result = client.sync_nodes_to_federation(federation)

    assert result["synced"] == 1
    node = federation.get_node("web-phone")
    assert node is not None
    assert node["permissions"] == ["publish_capabilities", "request_compute"]
    assert node["capabilities"]["model_support"]["recommended_use"] == "browser_preprocess"
    assert node["capability_status"] == "medium"


def test_benchmark_online_nodes_updates_model_feed(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/nodes":
            return httpx.Response(
                200,
                json={
                    "nodes": [
                        {
                            "node_id": "web-tablet",
                            "display_name": "Tablet",
                            "online": True,
                            "capabilities": {"cpu_count": 8, "device_memory_gb": 8},
                        }
                    ]
                },
            )
        if request.url.path == "/api/jobs" and request.method == "POST":
            return httpx.Response(200, json={"status": "ok", "job_id": "rjob-1"})
        if request.url.path == "/api/jobs" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "job_id": "rjob-1",
                            "node_id": "web-tablet",
                            "status": "completed",
                            "result": {"task": "browser_benchmark", "seconds": 1, "loops": 1000, "score": 1000},
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    federation = Federation(db_path=tmp_path / "triade.db")
    client = PublicRelayClient("https://relay.test", "admin", client=make_client(handler))

    result = client.benchmark_online_nodes(federation, seconds=1, wait_timeout=1)

    assert result["benchmarks"][0]["job"]["status"] == "completed"
    node = federation.get_node("web-tablet")
    assert node is not None
    assert node["capabilities"]["benchmark_score"] == 1000
    assert node["capabilities"]["compute_status"] == "ready"
    assert node["capabilities"]["model_support"]["can_host_llm"] is False


def test_preprocess_text_online_returns_model_feed(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/nodes":
            return httpx.Response(
                200,
                json={
                    "nodes": [
                        {
                            "node_id": "web-phone",
                            "display_name": "Celular",
                            "online": True,
                            "capabilities": {"cpu_count": 8, "device_memory_gb": 8},
                        }
                    ]
                },
            )
        if request.url.path == "/api/jobs" and request.method == "POST":
            payload = request.read().decode("utf-8")
            assert "preprocess_text" in payload
            return httpx.Response(200, json={"status": "ok", "job_id": "rjob-pre"})
        if request.url.path == "/api/jobs" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "job_id": "rjob-pre",
                            "node_id": "web-phone",
                            "status": "completed",
                            "result": {
                                "task": "preprocess_text",
                                "chars": 18,
                                "word_count": 3,
                                "approx_tokens": 5,
                                "keywords": [{"term": "triade", "count": 2}],
                                "chunks": [{"index": 0, "start": 0, "end": 18, "text": "triade usa nodos"}],
                            },
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    federation = Federation(db_path=tmp_path / "triade.db")
    client = PublicRelayClient("https://relay.test", "admin", client=make_client(handler))

    result = client.preprocess_text_online(federation, "triade usa nodos", wait_timeout=1)

    assert result["completed"] == 1
    assert result["model_feed"]["ready_for_local_model"] is True
    assert result["model_feed"]["keywords"][0]["term"] == "triade"
    assert result["model_feed"]["chunks"][0]["node_id"] == "web-phone"


def test_sync_native_android_node_marks_cpu_feed(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "nodes": [
                    {
                        "node_id": "android-phone",
                        "display_name": "Android nativo",
                        "online": True,
                        "capabilities": {
                            "native_android": True,
                            "app_node": True,
                            "background_execution": True,
                            "cpu_count": 8,
                            "ram_available_gb": 4,
                            "allowed_tasks": ["sha256", "preprocess_text"],
                        },
                    }
                ]
            },
        )

    federation = Federation(db_path=tmp_path / "triade.db")
    client = PublicRelayClient("https://relay.test", "admin", client=make_client(handler))

    client.sync_nodes_to_federation(federation)
    node = federation.get_node("android-phone")

    assert node is not None
    support = node["capabilities"]["model_support"]
    assert node["capabilities"]["native_android"] is True
    assert support["recommended_use"] == "android_native_cpu_feed"
    assert "background_cpu_feed" in support["can_assist"]

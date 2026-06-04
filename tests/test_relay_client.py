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

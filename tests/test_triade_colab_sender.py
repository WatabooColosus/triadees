"""Sender tests ensure Colab never uploads raw memory or private events."""

from __future__ import annotations

import json

import pytest

from tools import triade_colab_outbound_telemetry as sender

TEST_TOKEN = "test-colab-" + "k" * 40


def test_colab_sender_allowlists_only_local_runtime_gets(monkeypatch):
    local_calls = []

    def fake_get(path):
        local_calls.append(path)
        if path == "/health/live":
            return {"status": "ok", "user_secret": "do-not-send"}
        if path == "/api/runtime/heartbeat":
            return {
                "api_server_alive": True,
                "runtime_enabled": True,
                "workers_active": False,
                "heartbeat_cycle": 12,
                "mode": "observe_only",
                "raw_memory": "do-not-send",
            }
        if path == "/api/runtime/learning-journal":
            return {
                "cycles_last_24h": 4,
                "candidates_consolidated": 2,
                "latest_events": [{"body": "private-memory"}],
                "semantic_documents_activity": {
                    "count": 3,
                    "latest": [{"body": "private"}],
                },
            }
        raise AssertionError(path)

    monkeypatch.setattr(sender, "_get", fake_get)
    data = sender.collect_once()
    assert local_calls == [
        "/health/live",
        "/api/runtime/heartbeat",
        "/api/runtime/learning-journal",
    ]
    assert data["schema_version"] == 1
    assert data["observations"]["workers_active"] is False
    assert data["stats"] == {
        "cycles_last_24h": 4,
        "candidates_consolidated": 2,
        "semantic_documents_count": 3,
    }
    assert "private-memory" not in str(data)
    assert "do-not-send" not in str(data)


def test_colab_sender_does_not_post_without_token_or_local_runtime(monkeypatch):
    monkeypatch.delenv("TRIADE_TELEMETRY_INGEST_TOKEN", raising=False)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("No remote HTTP is allowed")

    monkeypatch.setattr(sender.urllib.request, "urlopen", forbidden)
    with pytest.raises(RuntimeError, match="telemetry_secret_not_configured"):
        sender.send_once()

    monkeypatch.setenv("TRIADE_TELEMETRY_INGEST_TOKEN", TEST_TOKEN)
    monkeypatch.setattr(
        sender, "collect_once", lambda: (_ for _ in ()).throw(RuntimeError("offline"))
    )
    with pytest.raises(RuntimeError, match="offline"):
        sender.send_once()


def test_colab_sender_posts_exact_fixed_https_endpoint(monkeypatch):
    monkeypatch.setenv("TRIADE_TELEMETRY_INGEST_TOKEN", TEST_TOKEN)
    report = {
        "schema_version": 1,
        "observations": {"api_server_alive": True},
        "stats": {"cycles_last_24h": 2},
    }
    monkeypatch.setattr(sender, "collect_once", lambda: report)
    captured = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _size=-1):
            return b'{"accepted":true,"certified":false}'

    def fake_urlopen(request, timeout):
        captured.append((request, timeout))
        return Response()

    monkeypatch.setattr(sender.urllib.request, "urlopen", fake_urlopen)
    result = sender.send_once()
    assert result == {"submitted": True, "certified": False}
    assert len(captured) == 1
    request, timeout = captured[0]
    assert request.full_url == (
        "https://triade-omega-mcp.onrender.com/api/telemetry/ingest"
    )
    assert request.get_method() == "POST"
    assert json.loads(request.data) == report
    assert request.headers["Authorization"] == "Bearer " + TEST_TOKEN
    assert timeout <= 20


def test_colab_sender_rejects_bad_local_path():
    with pytest.raises(ValueError, match="non_allowlisted_local_path"):
        sender._get("/api/run")

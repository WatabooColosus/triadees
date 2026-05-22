"""Tests del adaptador HTTP de embeddings Ollama 1.9B."""

from __future__ import annotations

import json
from unittest.mock import patch

from triade.models.ollama_client import OllamaClient


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_embed_calls_official_ollama_embed_endpoint() -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.method
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "model": "nomic-embed-text:latest",
                "embeddings": [[0.11, 0.22, 0.33]],
                "total_duration": 200,
                "load_duration": 10,
                "prompt_eval_count": 5,
            }
        )

    client = OllamaClient(base_url="http://127.0.0.1:11434", timeout=30)
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = client.embed("nomic-embed-text:latest", "Memoria de prueba")

    assert result.ok is True
    assert result.dimensions == 3
    assert result.embeddings == [[0.11, 0.22, 0.33]]
    assert captured["url"] == "http://127.0.0.1:11434/api/embed"
    assert captured["method"] == "POST"
    assert captured["payload"] == {
        "model": "nomic-embed-text:latest",
        "input": "Memoria de prueba",
        "truncate": True,
    }
    assert captured["timeout"] == 30


def test_embed_rejects_empty_input_without_http_call() -> None:
    client = OllamaClient()
    with patch("urllib.request.urlopen") as urlopen:
        result = client.embed("nomic-embed-text:latest", "  ")

    assert result.ok is False
    assert "vacío" in str(result.error)
    urlopen.assert_not_called()


def test_embed_reports_invalid_response() -> None:
    client = OllamaClient()
    with patch("urllib.request.urlopen", return_value=FakeResponse({"model": "nomic-embed-text:latest"})):
        result = client.embed("nomic-embed-text:latest", "Texto")

    assert result.ok is False
    assert "embeddings válidos" in str(result.error)

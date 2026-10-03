"""Contrato HTTP mínimo de llama.cpp como motor local alternativo."""

from __future__ import annotations

import json
from typing import Any

from triade.models.llamacpp_client import LlamaCppClient
from triade.models.model_client_factory import (
    build_model_client,
    default_model_base_url,
    normalize_model_provider,
)


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None


def test_factory_normalizes_llamacpp_aliases() -> None:
    assert normalize_model_provider("llamacpp") == "llama.cpp"
    assert normalize_model_provider("llama_cpp") == "llama.cpp"
    assert default_model_base_url("llama.cpp") == "http://127.0.0.1:8080"
    assert isinstance(build_model_client("llamacpp"), LlamaCppClient)


def test_llamacpp_health_reads_openai_models(monkeypatch) -> None:
    def fake_urlopen(request, timeout=None):
        assert request.full_url.endswith("/v1/models")
        return _Response({"data": [{"id": "qwen3.5:2b"}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    health = LlamaCppClient().health()
    assert health["ok"] is True
    assert health["models"] == ["qwen3.5:2b"]
    assert health["provider"] == "llama.cpp"


def test_llamacpp_generate_maps_chat_completion(monkeypatch) -> None:
    captured: list[dict[str, Any]] = []

    def fake_urlopen(request, timeout=None):
        captured.append(json.loads(request.data.decode()))
        return _Response(
            {
                "model": "qwen3.5:2b",
                "choices": [{"message": {"content": "respuesta local"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = LlamaCppClient().generate(
        "qwen3.5:2b",
        "hola",
        system="eres Tríade",
        options={"temperature": 0, "num_predict": 64},
        use_active_peft=True,
    )
    assert result.ok is True
    assert result.provider == "llama.cpp"
    assert result.text == "respuesta local"
    assert captured[0]["max_tokens"] == 64
    assert captured[0]["messages"][0]["role"] == "system"


def test_llamacpp_embeddings_use_openai_endpoint(monkeypatch) -> None:
    def fake_urlopen(request, timeout=None):
        payload = json.loads(request.data.decode())
        assert payload["input"] == "memoria"
        return _Response(
            {
                "model": "embed-small",
                "data": [{"embedding": [0.1, 0.2, 0.3]}],
                "usage": {"prompt_tokens": 2},
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = LlamaCppClient().embed("embed-small", "memoria")
    assert result.ok is True
    assert result.provider == "llama.cpp"
    assert result.embeddings == [[0.1, 0.2, 0.3]]

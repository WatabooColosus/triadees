from __future__ import annotations

from triade.models.llamacpp_client import LlamaCppClient
from triade.models.model_client_factory import create_model_client


def test_factory_selects_llama_cpp_without_ollama() -> None:
    client = create_model_client("llama.cpp", model_path="model.gguf")
    assert isinstance(client, LlamaCppClient)
    assert client.provider == "llama.cpp"
    assert client.health()["ok"] is True


def test_llama_cpp_missing_engine_is_degraded_and_traceable() -> None:
    client = LlamaCppClient(model_path="")
    result = client.generate("local", "hola")
    assert result.ok is False
    assert result.provider == "llama.cpp"
    assert result.error

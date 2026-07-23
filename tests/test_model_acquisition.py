from unittest.mock import patch

from triade.core.model_acquisition import MODEL_CATALOG, assign_models_to_neurons, ensure_specialized_model_neurons, reconcile_model_catalog
from triade.core.foundational_neurons import ensure_foundational_neurons


def test_catalog_has_provenance_license_and_budget():
    assert set(MODEL_CATALOG) == {"qwen3:4b", "qwen2.5-coder:3b", "gemma3:4b"}
    assert all(item["source"].startswith("https://ollama.com/library/") for item in MODEL_CATALOG.values())
    assert all(item["license"] and item["size_gb"] > 0 for item in MODEL_CATALOG.values())


def test_reconcile_never_downloads_outside_catalog(tmp_path, monkeypatch):
    with patch("triade.core.model_acquisition.OllamaClient.health", return_value={"models": list(MODEL_CATALOG)}), \
         patch("triade.core.model_acquisition.subprocess.run") as run:
        result = reconcile_model_catalog(db_path=tmp_path / "triade.db")
    assert result["downloaded"] == []
    run.assert_not_called()


def test_assignments_preserve_innate_default(tmp_path):
    db = tmp_path / "triade.db"
    ensure_foundational_neurons(db)
    with patch("triade.core.model_acquisition.OllamaClient.health", return_value={"models": ["triade-omega:latest"]}):
        result = assign_models_to_neurons(db)
    assert len(result) == 10
    assert all(item["model"] == "triade-omega:latest" for item in result)


def test_specialized_neurons_receive_specialized_models(tmp_path):
    db = tmp_path / "triade.db"
    ensure_foundational_neurons(db)
    from triade.core.neuron_creator import NeuronSpec
    from triade.core.neuron_registry import NeuronRegistry
    registry = NeuronRegistry(db)
    registry.register(NeuronSpec(name="Neurona de imágenes", mission="Analizar imágenes", domain="vision", status="experimental"))
    registry.register(NeuronSpec(name="Neurona reparadora", mission="Reparar código", domain="code_repair", status="experimental"))
    installed = ["triade-omega:latest", "gemma3:4b", "qwen2.5-coder:3b"]
    with patch("triade.core.model_acquisition.OllamaClient.health", return_value={"models": installed}):
        result = {item["neuron"]: item["model"] for item in assign_models_to_neurons(db)}
    assert result["Neurona de imágenes"] == "gemma3:4b"
    assert result["Neurona reparadora"] == "qwen2.5-coder:3b"


def test_specialized_model_neurons_remain_experimental(tmp_path):
    db = tmp_path / "triade.db"
    ensure_specialized_model_neurons(db)
    from triade.core.neuron_registry import NeuronRegistry
    neurons = {n["name"]: n for n in NeuronRegistry(db).list_neurons(limit=10)}
    assert neurons["Neurona Visual"]["status"] == "experimental"
    assert neurons["Neurona de Código y Reparación"]["status"] == "experimental"

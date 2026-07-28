from pathlib import Path

from triade.models.model_router import ModelRouter


REPO_ROOT = Path(__file__).resolve().parents[1]


def _declared_models() -> set[str]:
    lines = (REPO_ROOT / "config" / "studio-models.txt").read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")}


def test_studio_catalog_covers_critical_model_roles() -> None:
    models = _declared_models()

    assert "qwen2.5:3b-instruct" in models
    assert "qwen2.5-coder:3b" in models
    assert "nomic-embed-text:latest" in models
    for role in ("central", "coder", "embedding", "fast", "deep"):
        decision = ModelRouter(available_models=sorted(models)).route(role)
        assert decision.fallback_used is False
        assert decision.selected_model in models


def test_studio_ollama_scripts_use_persistent_storage() -> None:
    for name in (
        "install_studio_ollama.sh",
        "start_studio_ollama.sh",
        "ensure_studio_models.sh",
        "verify_studio_models.sh",
    ):
        content = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "TRIADE_STUDIO_OLLAMA_ROOT" in content
        assert ".ollama" in content

"""Tests de cola segura de instalación de modelos."""

from __future__ import annotations

from triade.models.hardware_profile import HardwareProfile
from triade.models.model_install_queue import ModelInstallQueue


def hw(tier: str = "medium", available: float = 8.0, disk: float = 100.0) -> HardwareProfile:
    return HardwareProfile(
        cpu_count=8,
        ram_total_gb=16.0,
        ram_available_gb=available,
        tier=tier,
        notes=[],
        disk_free_gb=disk,
    )


def test_install_queue_has_policy() -> None:
    queue = ModelInstallQueue(hw(), available_models=[])
    payload = queue.build(include_allowed=True)

    assert payload["status"] == "ok"
    assert payload["mode"] == "install-queue"
    assert payload["policy"]["auto_install"] is False
    assert payload["policy"]["requires_authorization"] is True


def test_install_queue_skips_installed_models() -> None:
    queue = ModelInstallQueue(hw(), available_models=["qwen2.5:3b-instruct", "nomic-embed-text:latest"])
    payload = queue.build(include_allowed=True)
    models = {item["model"] for item in payload["candidates"]}

    assert "qwen2.5:3b-instruct" not in models
    assert "nomic-embed-text:latest" not in models


def test_install_queue_generates_ollama_pull_command() -> None:
    queue = ModelInstallQueue(hw(), available_models=[])
    payload = queue.build(include_allowed=True)

    assert payload["candidates"]
    assert payload["candidates"][0]["command"].startswith("ollama pull ")
    assert payload["candidates"][0]["authorized"] is False


def test_install_queue_warns_when_disk_low() -> None:
    queue = ModelInstallQueue(hw(disk=1.0), available_models=[])
    payload = queue.build(include_allowed=True)

    assert any(
        "Disco libre insuficiente" in " ".join(item["warnings"])
        for item in payload["candidates"]
    )

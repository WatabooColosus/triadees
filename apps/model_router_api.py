"""API local para consultar recomendaciones de modelos."""

from __future__ import annotations

from fastapi import FastAPI

from triade.models.hardware_profile import HardwareProfiler
from triade.models.model_router import ModelRouter
from triade.models.ollama_client import OllamaClient

app = FastAPI(title="Triade Model Router API", version="0.2.0")


def build_router() -> tuple[dict, object, ModelRouter]:
    client = OllamaClient()
    ollama = client.health()
    hardware = HardwareProfiler().detect()
    router = ModelRouter(available_models=ollama.get("models", []), hardware=hardware)
    return ollama, hardware, router


@app.get("/health")
def health() -> dict:
    ollama, hardware, router = build_router()
    return {
        "status": "ok",
        "service": "triade-model-router",
        "ollama": ollama,
        "hardware": hardware.to_dict(),
        "roles": sorted(router.DEFAULTS.keys()),
    }


@app.get("/models/doctor")
def models_doctor(intent: str = "conversation", urgency: str = "medium") -> dict:
    ollama, hardware, router = build_router()
    return {
        "status": "ok",
        "ollama": ollama,
        "hardware": hardware.to_dict(),
        "router": router.route_many(intent=intent, urgency=urgency),
    }

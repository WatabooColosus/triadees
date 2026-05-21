"""API local para consultar recomendaciones de modelos."""

from __future__ import annotations

from fastapi import FastAPI

from triade.models.model_router import ModelRouter
from triade.models.ollama_client import OllamaClient

app = FastAPI(title="Triade Model Router API", version="0.1.0")


@app.get("/health")
def health() -> dict:
    client = OllamaClient()
    ollama = client.health()
    router = ModelRouter(available_models=ollama.get("models", []))
    return {
        "status": "ok",
        "service": "triade-model-router",
        "ollama": ollama,
        "roles": sorted(router.DEFAULTS.keys()),
    }


@app.get("/models/doctor")
def models_doctor(intent: str = "conversation", urgency: str = "medium") -> dict:
    client = OllamaClient()
    ollama = client.health()
    router = ModelRouter(available_models=ollama.get("models", []))
    return {
        "status": "ok",
        "ollama": ollama,
        "router": router.route_many(intent=intent, urgency=urgency),
    }

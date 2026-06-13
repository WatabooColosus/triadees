"""API local FastAPI para Tríade Ω.

DEPRECATED_UI: Migrated to single_port_app.py. Keep until v2.4.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from triade import __version__
from triade.core.neuron_registry import NeuronRegistry
from triade.core.runner import TriadeRunner

API_KEY_ENV = "TRIADE_API_KEY"
CORS_ORIGINS_ENV = "TRIADE_CORS_ORIGINS"


def _cors_origins() -> list[str]:
    raw = os.getenv(CORS_ORIGINS_ENV, "http://127.0.0.1:5678,http://localhost:5678")
    return [item.strip() for item in raw.split(",") if item.strip()]


app = FastAPI(
    title="Tríade Ω Local API",
    version=__version__,
    description="API local para ejecutar runs auditables de Tríade Ω.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-TRIADE-API-Key"],
)


class RunRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Entrada del usuario para Tríade")
    source: str = Field(default="api", description="Fuente del run")
    runs_dir: str = Field(default="runs", description="Carpeta de runs")
    db_path: str = Field(default="triade/memory/triade.db", description="Ruta SQLite")
    config_path: str = Field(default="triade.yml", description="Ruta de configuración")
    use_ollama: bool = Field(default=True, description="Usar Ollama si está disponible")
    hypothalamus_model: str | None = Field(default=None, description="Modelo de Hipotálamo")
    central_model: str | None = Field(default=None, description="Modelo de Central")


class RecallResponse(BaseModel):
    query: str
    count: int
    episodes: list[dict[str, Any]]


def api_key_enabled() -> bool:
    return bool(os.getenv(API_KEY_ENV))


def require_api_key(x_triade_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv(API_KEY_ENV)
    if not expected:
        return
    if x_triade_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida o ausente.",
        )


def build_runner(
    runs_dir: str = "runs",
    db_path: str = "triade/memory/triade.db",
    config_path: str = "triade.yml",
    use_ollama: bool = True,
    hypothalamus_model: str | None = None,
    central_model: str | None = None,
) -> TriadeRunner:
    return TriadeRunner(
        runs_dir=runs_dir,
        db_path=db_path,
        config_path=config_path,
        use_ollama=use_ollama,
        hypothalamus_model=hypothalamus_model,
        central_model=central_model,
    )


@app.get("/health")
def health() -> dict[str, Any]:
    runner = build_runner(use_ollama=False)
    doctor = runner.doctor()
    return {
        "status": "ok",
        "entity": "Tríade Ω",
        "version": __version__,
        "security": {
            "api_key_required": api_key_enabled(),
            "cors_origins": _cors_origins(),
        },
        "doctor": doctor,
    }


@app.post("/triade/run", dependencies=[Depends(require_api_key)])
def triade_run(request: RunRequest) -> dict[str, Any]:
    runner = build_runner(
        runs_dir=request.runs_dir,
        db_path=request.db_path,
        config_path=request.config_path,
        use_ollama=request.use_ollama,
        hypothalamus_model=request.hypothalamus_model,
        central_model=request.central_model,
    )
    return runner.run(request.text, source=request.source)


@app.get("/triade/recall", response_model=RecallResponse, dependencies=[Depends(require_api_key)])
def triade_recall(query: str = "", limit: int = 10) -> dict[str, Any]:
    runner = build_runner(use_ollama=False)
    return runner.recall(query=query, limit=limit)


@app.get("/triade/doctor", dependencies=[Depends(require_api_key)])
def triade_doctor(use_ollama: bool = True) -> dict[str, Any]:
    runner = build_runner(use_ollama=use_ollama)
    return runner.doctor()


@app.get("/triade/neurons", dependencies=[Depends(require_api_key)])
def triade_neuron_list(limit: int = 20, db_path: str = "triade/memory/triade.db") -> dict[str, Any]:
    registry = NeuronRegistry(db_path=db_path)
    neurons = registry.list_neurons(limit=limit)
    return {"status": "ok", "count": len(neurons), "neurons": neurons}


@app.get("/triade/neurons/{name}", dependencies=[Depends(require_api_key)])
def triade_neuron_show(name: str, limit: int = 10, db_path: str = "triade/memory/triade.db") -> dict[str, Any]:
    registry = NeuronRegistry(db_path=db_path)
    neuron = registry.get_neuron(name)
    if neuron is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Neurona no encontrada.")
    training = registry.list_training(neuron_id=int(neuron["id"]), limit=limit)
    return {"status": "ok", "neuron": neuron, "training": training}





# Compatibilidad: el CLI `triade_digimon.py api` usa esta app legacy.
# Incluimos las rutas single-port para que UI/observabilidad no diverjan.
from apps.routes.api import router as single_port_api_router  # noqa: E402
from apps.routes.ui import router as single_port_ui_router  # noqa: E402

app.include_router(single_port_api_router)
app.include_router(single_port_ui_router)

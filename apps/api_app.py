"""API local FastAPI para Tríade Ω."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from triade import __version__
from triade.core.runner import TriadeRunner

app = FastAPI(
    title="Tríade Ω Local API",
    version=__version__,
    description="API local para ejecutar runs auditables de Tríade Ω.",
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
        "doctor": doctor,
    }


@app.post("/triade/run")
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


@app.get("/triade/recall", response_model=RecallResponse)
def triade_recall(query: str = "", limit: int = 10) -> dict[str, Any]:
    runner = build_runner(use_ollama=False)
    return runner.recall(query=query, limit=limit)


@app.get("/triade/doctor")
def triade_doctor(use_ollama: bool = True) -> dict[str, Any]:
    runner = build_runner(use_ollama=use_ollama)
    return runner.doctor()

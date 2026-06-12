"""Esquemas Pydantic para fronteras API de Tríade Ω.

Centraliza los modelos de validación para requests/responses del API,
eliminando duplicados entre apps/services.py, apps/api_app.py y apps/routes/api.py.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    text: str = Field(..., min_length=1)
    source: str = "single-port-ui"
    use_ollama: bool = True
    hypothalamus_model: str | None = None
    central_model: str | None = None
    auto_select_models: bool = True
    context: dict[str, Any] = Field(default_factory=dict)
    conversation_history: list[dict[str, str]] = Field(default_factory=list)
    semantic_recall_enabled: bool = False
    semantic_model: str | None = None
    semantic_limit: int = Field(default=3, ge=1, le=20)
    semantic_min_similarity: float = Field(default=0.55, ge=-1.0, le=1.0)
    semantic_domain: str | None = None
    semantic_allow_experimental: bool = False


class RunApiRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Entrada del usuario para Tríade")
    source: str = Field(default="api", description="Fuente del run")
    runs_dir: str = Field(default="runs", description="Carpeta de runs")
    db_path: str = Field(default="triade/memory/triade.db", description="Ruta SQLite")
    config_path: str = Field(default="triade.yml", description="Ruta de configuración")
    use_ollama: bool = Field(default=True, description="Usar Ollama si está disponible")
    hypothalamus_model: str | None = Field(default=None, description="Modelo de Hipotálamo")
    central_model: str | None = Field(default=None, description="Modelo de Central")


class RouterRequest(BaseModel):
    intent: str = "conversation"
    urgency: str = "medium"


class SemanticIngestRequest(BaseModel):
    content: str = Field(..., min_length=1)
    domain: str = "general"
    source_type: str = "manual"
    source_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None


class SemanticEmbedRequest(BaseModel):
    model: str | None = None


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    model: str | None = None
    limit: int = Field(default=5, ge=1, le=50)
    min_similarity: float = Field(default=-1.0, ge=-1.0, le=1.0)
    domain: str | None = None


class SemanticTransitionRequest(BaseModel):
    new_status: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class NeuronCandidateDecisionRequest(BaseModel):
    candidate_id: int
    decision: str = Field(..., pattern="^(promote|reject)$")
    reason: str = Field(default="", max_length=500)


class RecallResponse(BaseModel):
    query: str
    count: int
    episodes: list[dict[str, Any]]


class BodegaGlobalContextResponse(BaseModel):
    status: str
    mode: str = ""
    memory_confidence: str = "low"
    memory_confidence_score: float = 0.0
    continuity_summary: str = ""
    recommended_context_policy: str = "ask_or_operate_with_limited_memory"
    contradictions_count: int = 0
    semantic_matches_count: int = 0
    recent_episodes_count: int = 0
    stable_needs_review: int = 0
    semantic_engine_status: str = "unavailable"
    semantic_engine_error: str | None = None


class MemoryTraceResponse(BaseModel):
    run_id: str
    memory_confidence: str = "low"
    memory_confidence_score: float = 0.0
    identity_matches_count: int = 0
    semantic_matches_count: int = 0
    episodic_matches_count: int = 0
    authorized_matches_count: int = 0
    quarantined_matches_count: int = 0
    contradictions_count: int = 0
    stable_needs_review: int = 0
    runtime_continuity_score: float = 0.0
    created_at: str | None = None


class LivingReportResponse(BaseModel):
    status: str
    runtime_enabled: bool = False
    runtime_mode: str | None = None
    cycles_last_hour: int = 0
    missions_executed_last_hour: int = 0
    learning_candidates_created_last_hour: int = 0
    workers_active: bool = False
    runtime_continuity_score: float = 0.0
    bodega_global_context_summary: dict[str, Any] = Field(default_factory=dict)
    stable_neuron_audit: dict[str, Any] = Field(default_factory=dict)

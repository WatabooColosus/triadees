from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import apps.routes.api as api_module
from apps.single_port_app import app
from triade.core.internal_runtime import build_runtime_heartbeat
from triade.core.ollama_blood import check_ollama_blood, ollama_blood_policy
from triade.core.neuron_nutrition import run_neuron_nutrition_cycle
from triade.learning.pipeline import LearningPipeline


OFFLINE_BLOOD = {
    "status": "degraded_no_ollama",
    "ok": False,
    "ollama_ok": False,
    "mode": "fallback_breathing",
    "base_url": "http://127.0.0.1:11434",
    "models_available": [],
    "reasoning_model": None,
    "embedding_model": None,
    "coder_model": None,
    "latency_ms": 0.1,
    "can_reason": False,
    "can_embed": False,
    "can_nourish_neurons": False,
    "can_evaluate_learning": False,
    "can_consolidate_stable": False,
    "degraded_components": ["neuron_nutrition", "learning_evaluation", "semantic_embedding"],
    "recommended_action": "Iniciar Ollama.",
    "blood_pressure_score": 0.0,
    "checked_at": "2026-06-13T00:00:00+00:00",
    "cognitive_blood_active": False,
    "fallback_mode": True,
}


FULL_BLOOD = {
    **OFFLINE_BLOOD,
    "status": "ok",
    "ok": True,
    "ollama_ok": True,
    "mode": "cognitive_blood_active",
    "models_available": ["qwen2.5:3b-instruct", "nomic-embed-text:latest", "qwen2.5-coder:3b"],
    "reasoning_model": "qwen2.5:3b-instruct",
    "embedding_model": "nomic-embed-text:latest",
    "coder_model": "qwen2.5-coder:3b",
    "can_reason": True,
    "can_embed": True,
    "can_nourish_neurons": True,
    "can_evaluate_learning": True,
    "can_consolidate_stable": True,
    "degraded_components": [],
    "recommended_action": "Sangre cognitiva activa.",
    "blood_pressure_score": 1.0,
    "cognitive_blood_active": True,
    "fallback_mode": False,
}


def test_ollama_blood_degraded_when_ollama_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "triade.core.ollama_blood.OllamaClient.health",
        lambda self: {"ok": False, "base_url": self.base_url, "models": [], "error": "offline"},
    )
    blood = check_ollama_blood()
    assert blood["status"] == "degraded_no_ollama"
    assert blood["blood_pressure_score"] == 0.0
    assert blood["can_nourish_neurons"] is False


def test_ollama_blood_policy_blocks_neuron_nutrition_without_reasoning() -> None:
    policy = ollama_blood_policy("neuron_nutrition", OFFLINE_BLOOD)
    assert policy["allowed"] is False
    assert policy["degraded"] is True
    assert "propose_learning" in policy["blocked_actions"]


def test_ollama_blood_policy_allows_chat_fallback() -> None:
    policy = ollama_blood_policy("chat_response", OFFLINE_BLOOD)
    assert policy["allowed"] is True
    assert policy["fallback_allowed"] is True
    assert policy["degraded"] is True


def test_neuron_nutrition_forces_observe_only_without_blood(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("triade.core.neuron_nutrition.check_ollama_blood", lambda: OFFLINE_BLOOD)
    result = run_neuron_nutrition_cycle(db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs", mode="execute_missions")
    assert result["mode"] == "observe_only"
    assert result["cognitive_blood_active"] is False
    assert result["missions_executed"] == 0
    assert result["candidates_created"] == 0


def test_learning_evaluation_requires_blood_or_human_approval(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("triade.learning.pipeline.check_ollama_blood", lambda: OFFLINE_BLOOD)
    pipe = LearningPipeline(db_path=tmp_path / "triade.db", enforce_model_policy=True)
    cid = pipe.ingest(
        content="Candidato con evidencia, pero sin sangre cognitiva.",
        source_type="document",
        source_ref="doc:blood",
    )["candidate_id"]
    blocked = pipe.evaluate(cid)
    assert blocked["status"] == "requires_model"
    assert blocked["reason"] == "Ollama Blood no disponible para evaluación cognitiva."
    assert pipe.get_candidate(cid)["status"] == "candidate"
    approved = pipe.evaluate(cid, human_approval="santiago")
    assert approved["status"] == "evaluated"


def test_bodega_global_reports_blood_status(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("triade.core.bodega_global_context.check_ollama_blood", lambda: OFFLINE_BLOOD)
    from triade.core.bodega_global_context import build_bodega_global_context

    result = build_bodega_global_context("test", db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs")
    assert result["ollama_blood"]["status"] == "degraded_no_ollama"
    assert result["semantic_learning_allowed"] is False
    assert result["semantic_recall_mode"] in {"degraded_no_ollama", "keyword_only"}


def test_runtime_heartbeat_includes_blood_status(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("triade.core.ollama_blood.check_ollama_blood", lambda: OFFLINE_BLOOD)
    result = build_runtime_heartbeat(db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs", limit=5)
    assert result["ollama_blood"]["status"] == "degraded_no_ollama"
    assert result["blood_pressure_score"] == 0.0
    assert result["can_nourish_neurons"] is False


def test_api_ollama_blood_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "check_ollama_blood", lambda: FULL_BLOOD)
    client = TestClient(app)
    response = client.get("/api/models/ollama/blood")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["reasoning_model"] == "qwen2.5:3b-instruct"

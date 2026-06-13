from __future__ import annotations

from pathlib import Path

from triade.core.bodega_global_context import build_bodega_global_context
from triade.core.internal_runtime import build_runtime_heartbeat
from triade.core.model_policy import get_model_cognitive_policy
from triade.core.neuron_nutrition import run_neuron_nutrition_cycle
from triade.learning.pipeline import LearningPipeline


NO_OLLAMA_HEALTH = {
    "ok": False,
    "base_url": "http://127.0.0.1:11434",
    "models_available": [],
    "models": [],
    "required_models_present": False,
    "embedding_model_available": False,
    "reasoning_model_available": False,
    "coder_model_available": False,
    "latency_ms": 0,
    "errors": ["offline"],
    "recommended_action": "Iniciar Ollama.",
    "selected_models": {
        "reasoning": "qwen2.5:3b-instruct",
        "coding": "qwen2.5-coder:3b",
        "embeddings": "nomic-embed-text:latest",
        "lightweight": "qwen3:4b",
    },
    "degraded_functions": ["neuron_nutrition", "learning_evaluation", "semantic_embedding"],
    "mode": "degraded_no_ollama",
}

NO_OLLAMA_BLOOD = {
    "status": "degraded_no_ollama",
    "ok": False,
    "ollama_ok": False,
    "mode": "fallback_breathing",
    "base_url": "http://127.0.0.1:11434",
    "models_available": [],
    "reasoning_model": None,
    "embedding_model": None,
    "coder_model": None,
    "latency_ms": 0,
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


def test_model_policy_blocks_learning_without_ollama() -> None:
    policy = get_model_cognitive_policy("neuron_nutrition", ollama_available=False)
    assert policy["status"] == "degraded"
    assert policy["allowed_actions"]["allow_learning_write"] is False
    assert policy["allowed_actions"]["allow_stable_memory_write"] is False


def test_model_policy_allows_chat_fallback_without_ollama() -> None:
    policy = get_model_cognitive_policy("chat_response", ollama_available=False)
    assert policy["status"] == "fallback"
    assert policy["allowed_actions"]["allow_response"] is True
    assert policy["allowed_actions"]["response_must_disclose_degraded_mode"] is True


def test_neuron_nutrition_no_ollama_observe_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("triade.core.neuron_nutrition.check_ollama_blood", lambda: NO_OLLAMA_BLOOD)
    result = run_neuron_nutrition_cycle(db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs", mode="execute_missions")
    assert result["mode"] == "observe_only"
    assert result["degraded_mode"] is True
    assert result["learning_allowed"] is False
    assert result["stable_write_allowed"] is False
    assert result["candidates_created"] == 0


def test_learning_evaluation_requires_model_or_human_approval(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("triade.learning.pipeline.check_ollama_blood", lambda: NO_OLLAMA_BLOOD)
    pipe = LearningPipeline(db_path=tmp_path / "triade.db", enforce_model_policy=True)
    cid = pipe.ingest(
        content="Aprendizaje candidato con fuente, pero sin motor cognitivo disponible.",
        source_type="document",
        source_ref="doc:test",
        title="Candidato con modelo requerido",
    )["candidate_id"]
    evaluated = pipe.evaluate(cid)
    assert evaluated["status"] == "requires_model"
    assert pipe.get_candidate(cid)["status"] == "candidate"

    approved = pipe.evaluate(cid, human_approval="santiago")
    assert approved["status"] == "evaluated"


def test_bodega_global_reports_semantic_degraded_without_ollama(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("triade.core.bodega_global_context.check_ollama_blood", lambda: NO_OLLAMA_BLOOD)
    result = build_bodega_global_context("test", db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs")
    assert result["semantic_engine_status"] == "unavailable"
    assert result["semantic_learning_allowed"] is False
    assert result["ollama_required_for_semantic_recall"] is True


def test_runtime_heartbeat_reports_cognitive_model_status(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("triade.core.ollama_blood.check_ollama_blood", lambda: NO_OLLAMA_BLOOD)
    result = build_runtime_heartbeat(db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs", limit=5)
    assert result["cognitive_model_status"] == "degraded_no_ollama"
    assert result["can_nourish_neurons"] is False
    assert result["can_evaluate_learning"] is False

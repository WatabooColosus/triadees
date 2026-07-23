from __future__ import annotations

import sqlite3

import pytest

from triade.core.orchestrator_coord import CoordinationLock
from triade.core.safe_shell import AUTONOMOUS_SAFE_EXTENSIONS, run_autonomous
from triade.federation.peer_sync import PeerSync
from triade.models.ab_model_evaluator import ABModelEvaluator
from triade.models.ollama_client import ModelResult
from triade.workers.adaptive_scheduler import AdaptiveScheduler


def test_safe_shell_never_exposes_environment_and_confines_workdir(tmp_path):
    assert "env_keys" not in AUTONOMOUS_SAFE_EXTENSIONS
    result = run_autonomous("pwd", working_dir=tmp_path)
    assert result["status"] == "blocked"
    assert "dentro del proyecto" in result["error"]


def test_peer_registration_rejects_private_urls_and_schema_works(tmp_path):
    sync = PeerSync(tmp_path / "peer.db")
    with pytest.raises(ValueError, match="private"):
        sync.register_peer("local", "http://127.0.0.1:8010")

    # Avoid DNS/network dependence while proving the persistence schema itself.
    import triade.federation.peer_sync as peer_module
    original = peer_module._assert_public_url
    peer_module._assert_public_url = lambda _url: None
    try:
        sync.register_peer("remote", "https://peer.example")
    finally:
        peer_module._assert_public_url = original
    assert sync.get_peers()[0]["peer_id"] == "remote"


def test_ab_evaluator_uses_real_ollama_result_shape(tmp_path, monkeypatch):
    from triade.models import ollama_client

    monkeypatch.setattr(
        ollama_client.OllamaClient,
        "generate",
        lambda self, model, prompt, system=None: ModelResult(
            ok=True, text="respuesta comprobable suficientemente extensa para evaluar", model=model
        ),
    )
    evaluator = ABModelEvaluator(tmp_path / "ab.db")
    result = evaluator._run_model("test-model", "prompt", 2)
    assert result["status"] == "ok"
    assert result["output"].startswith("respuesta comprobable")


def test_ab_evaluator_reports_the_actual_model_name(tmp_path, monkeypatch):
    evaluator = ABModelEvaluator(tmp_path / "winner.db")
    responses = {
        "strong": {"status": "ok", "output": "porque " * 120, "duration_ms": 100},
        "weak": {"status": "error", "output": "", "duration_ms": 0},
    }
    monkeypatch.setattr(evaluator, "_run_model", lambda model, prompt, timeout: responses[model])
    result = evaluator.evaluate_pair("pulse_check", "strong", "weak")
    assert result["winner"] == "strong"
    assert result["evaluation_method"] == "internal_heuristic"
    assert result["counts_as_external_evidence"] is False


def test_coordination_lock_excludes_other_owner_and_expires(tmp_path):
    db_path = tmp_path / "locks.db"
    lock = CoordinationLock(db_path)
    assert lock.try_acquire("task", "one", ttl_seconds=10)
    assert not lock.try_acquire("task", "two", ttl_seconds=1)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE orchestrator_locks SET expires_at = 0 WHERE lock_key = 'task'")
    assert lock.try_acquire("task", "two", ttl_seconds=1)


def test_scheduler_returns_bounded_seconds(tmp_path):
    scheduler = AdaptiveScheduler(tmp_path / "scheduler.db")
    scheduler.record_task_execution("pulse_check", 100, True, resource_score=0.5)
    interval = scheduler.get_recommended_interval("pulse_check")
    assert scheduler.MIN_INTERVAL <= interval <= scheduler.MAX_INTERVAL
    assert interval < 1000  # seconds, never milliseconds

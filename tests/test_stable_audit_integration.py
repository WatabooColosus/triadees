"""Tests para la integración completa: stable_audit, context_engine, runner, central, workers."""

from __future__ import annotations

from pathlib import Path

from triade.core.living_report import build_living_report
from triade.core.context_engine import build_living_context_for_chat
from triade.core.neuron_creator import NeuronSpec
from triade.core.neuron_registry import NeuronRegistry


def test_living_report_includes_stable_neuron_audit(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    registry = NeuronRegistry(db_path=db_path)
    registry.register(NeuronSpec(
        name="neurona-lr-test",
        mission="Probar living report.",
        domain="system_governance",
        rules=["Solo prueba"],
        status="stable",
        created_by="test",
    ))
    report = build_living_report(db_path=db_path, runs_dir=runs_dir, limit=5)
    assert "stable_neuron_audit" in report
    audit = report["stable_neuron_audit"]
    assert audit["status"] in ("ok", "error")
    assert "total_stable_neurons" in audit
    assert "stable_with_enough_evidence" in audit
    assert "stable_needs_review" in audit
    assert "thresholds" in audit
    assert "policy" in audit
    assert "top_needs_review" in audit
    assert isinstance(audit["top_needs_review"], list)
    assert len(audit["top_needs_review"]) <= 10


def test_living_report_stable_audit_error_does_not_break_report(tmp_path: Path) -> None:
    db_path = tmp_path / "nonexistent" / "broken.db"
    report = build_living_report(db_path=db_path, runs_dir=tmp_path / "runs", limit=5)
    assert "stable_neuron_audit" in report
    audit = report["stable_neuron_audit"]
    assert audit["status"] in ("ok", "error")
    assert "total_stable_neurons" in audit
    assert "top_needs_review" in audit
    assert isinstance(audit["top_needs_review"], list)


def test_context_engine_includes_bodega_global_context(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    result = build_living_context_for_chat(
        user_input="¿qué sabes?",
        db_path=db_path,
        runs_dir=runs_dir,
        limit=5,
    )
    assert result["status"] == "ok"
    assert "bodega_global_context" in result
    bgc = result["bodega_global_context"]
    assert bgc["status"] in ("ok", "error")
    assert "memory_confidence" in bgc
    assert "recommended_context_policy" in bgc


def test_context_engine_chat_context_reports_global_usage(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    result = build_living_context_for_chat(
        user_input="test",
        db_path=db_path,
        runs_dir=runs_dir,
    )
    chat_ctx = result["chat_context"]
    assert "bodega_global_used" in chat_ctx
    assert "memory_confidence" in chat_ctx
    assert "recommended_context_policy" in chat_ctx


def test_context_engine_preserves_memory_context(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    result = build_living_context_for_chat(
        user_input="test",
        db_path=db_path,
        runs_dir=runs_dir,
    )
    assert "memory_context" in result
    mc = result["memory_context"]
    assert "recent_episodes" in mc
    assert "semantic_recall" in mc
    assert "learning_candidates_recent" in mc


def test_runner_semantic_recall_enabled_by_default(tmp_path: Path) -> None:
    from triade.core.runner import TriadeRunner
    runner = TriadeRunner(
        runs_dir=tmp_path / "runs",
        db_path=tmp_path / "triade.db",
        use_ollama=False,
    )
    result = runner.run(user_input="test runner", source="test")
    assert result["status"] == "ok"
    assert "run_id" in result


def test_runner_injects_bodega_global_context(tmp_path: Path) -> None:
    from triade.core.runner import TriadeRunner
    runner = TriadeRunner(
        runs_dir=tmp_path / "runs",
        db_path=tmp_path / "triade.db",
        use_ollama=False,
    )
    result = runner.run(user_input="contexto global test", source="test")
    assert result["status"] == "ok"
    run_artifacts = result.get("run_artifacts") or {}
    integrity = run_artifacts.get("integrity") or {}
    assert isinstance(integrity, dict)


def test_runner_no_identity_modification(tmp_path: Path) -> None:
    import sqlite3
    from triade.core.runner import TriadeRunner
    db_path = tmp_path / "triade.db"
    runner = TriadeRunner(
        runs_dir=tmp_path / "runs",
        db_path=db_path,
        use_ollama=False,
    )
    before = sqlite3.connect(str(db_path)).execute("SELECT COUNT(*) FROM identity_core").fetchone()[0]
    runner.run(user_input="modifica identidad core", source="test")
    after = sqlite3.connect(str(db_path)).execute("SELECT COUNT(*) FROM identity_core").fetchone()[0]
    assert before == after


def test_central_plan_includes_memory_confidence_steps(tmp_path: Path) -> None:
    from triade.core.central import Central
    from triade.core.contracts import InputPacket, SignalPacket, MemoryPacket, CrystalPacket, PlanPacket
    central = Central()
    input_packet = InputPacket(
        user_input="test",
        source="test",
        context={
            "bodega_global_context": {
                "status": "ok",
                "memory_confidence": "low",
                "recommended_context_policy": "ask_or_operate_with_limited_memory",
                "contradictions": ["test contradiction"],
                "stable_audit_summary": {"stable_needs_review": 2},
            }
        },
    )
    signals = SignalPacket(run_id="test", intent="conversation", tone="neutral", urgency="low", risk="low")
    memory = MemoryPacket(run_id="test")
    crystal = CrystalPacket(run_id="test")
    plan = central.plan(input_packet, signals, memory, crystal)
    steps_text = " ".join(plan.steps).lower()
    assert "memoria limitada" in steps_text or "limitada" in steps_text
    assert "contradicción" in steps_text or "contradicciones" in steps_text
    assert "revisión" in steps_text or "estabilidad" in steps_text


def test_central_plan_no_bodega_global_fallback(tmp_path: Path) -> None:
    from triade.core.central import Central
    from triade.core.contracts import InputPacket, SignalPacket, MemoryPacket, CrystalPacket
    central = Central()
    input_packet = InputPacket(user_input="test", source="test", context={})
    signals = SignalPacket(run_id="test", intent="conversation", tone="neutral", urgency="low", risk="low")
    memory = MemoryPacket(run_id="test")
    crystal = CrystalPacket(run_id="test")
    plan = central.plan(input_packet, signals, memory, crystal)
    assert len(plan.steps) >= 5


def test_worker_bodega_global_review_task_type_exists() -> None:
    from triade.workers.contracts import WORKER_TASK_TYPES
    assert "bodega_global_review" in WORKER_TASK_TYPES


def test_worker_bodega_global_review_handler_exists() -> None:
    from triade.workers.worker_loop import WorkerLoop
    assert hasattr(WorkerLoop, "_bodega_global_review")

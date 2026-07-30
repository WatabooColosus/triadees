"""Preflight del Runner: objetivos, web, contexto vivo e investigación candidata."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .error_bus import record_internal_error
from .runtime_scope import is_test_runtime


def prepare_input(
    packet: Any, user_input: str, source: str, db_path: Path, runs_dir: Path
) -> None:
    if not is_test_runtime() and not str(source).startswith(
        ("system_", "worker", "background", "test", "pytest")
    ):
        try:
            from .goal_orchestrator import GoalOrchestrator

            packet.context["goal_dispatch"] = GoalOrchestrator(db_path).accept(
                user_input, run_id=packet.run_id, source=source
            )
        except (
            OSError,
            ImportError,
            RuntimeError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ) as exc:
            record_internal_error(
                "runner.goal_orchestrator", exc, run_id=packet.run_id, db_path=db_path
            )
    try:
        from .guarded_web import guarded_web_research, requests_web_research

        if requests_web_research(user_input):
            packet.context["guarded_web_research"] = guarded_web_research(user_input)
    except (
        OSError,
        ImportError,
        RuntimeError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    ) as exc:
        record_internal_error(
            "runner.guarded_web_research", exc, run_id=packet.run_id, db_path=db_path
        )
    try:
        from .context_engine import build_living_context_for_chat

        living = build_living_context_for_chat(
            user_input, db_path=db_path, runs_dir=runs_dir, limit=20
        )
        packet.context.update(
            {
                "living_context": living,
                "triade_operational_awareness": living.get("internal_context", {}),
                "system_pulse_summary": (living.get("internal_context", {}) or {}).get(
                    "life_pulse", {}
                ),
                "bodega_global_context": living.get("bodega_global_context", {}),
            }
        )
    except (
        OSError,
        ImportError,
        RuntimeError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    ) as exc:
        record_internal_error(
            "runner.living_context", exc, run_id=packet.run_id, db_path=db_path
        )


def enrich_research(
    packet: Any, memory: Any, user_input: str, source: str, db_path: Path
) -> None:
    try:
        from triade.memory.continuity_truth import memory_truth_snapshot
        from triade.research import AutonomousResearchEngine

        packet.context["memory_truth"] = memory_truth_snapshot(db_path)
        existing = packet.context.get("guarded_web_research")
        engine = AutonomousResearchEngine(db_path)
        if isinstance(existing, dict) and existing.get("sources"):
            research = engine.ingest_result(
                user_input, existing, trigger="explicit_request"
            )
        else:
            should, trigger = engine.should_research(
                user_input,
                memory_confidence=float(memory.confidence or 0.0),
                authorized_matches=len(memory.semantic_matches or []),
            )
            research_result = (
                engine.research(user_input, trigger=trigger)
                if should
                and not is_test_runtime()
                and not str(source).startswith(("test", "pytest"))
                else None
            )
            research = research_result or {}
        if research:
            packet.context["guarded_web_research"] = research
            packet.context["autonomous_research"] = research
    except (
        OSError,
        ImportError,
        RuntimeError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    ) as exc:
        record_internal_error(
            "runner.autonomous_research", exc, run_id=packet.run_id, db_path=db_path
        )

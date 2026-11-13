from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from triade.evaluation.memory_longitudinal import run_memory_longitudinal_benchmark
from triade.memory.longitudinal import (
    LongitudinalMemory,
    MemoryObservation,
    MemoryScope,
)


def test_extractor_covers_all_governed_categories() -> None:
    extracted = LongitudinalMemory.extract(
        """Hecho: timezone=UTC
        Prefiero editor=Neovim
        Corrección: ciudad=Bogotá
        Relación: owner=Alice
        Decisión: database=SQLite
        Restricción: backup=required
        Proyecto: atlas=active
        Temporal: branch=feature/x""",
        "conversation:test",
    )
    assert {item.memory_type for item in extracted} == LongitudinalMemory.TYPES
    assert all(item.source_ref == "conversation:test" for item in extracted)


def test_candidates_never_influence_recall_and_explanation_is_present(
    tmp_path: Path,
) -> None:
    store = LongitudinalMemory(tmp_path / "memory.db")
    scope = MemoryScope("alice", "s1", "atlas", "work")
    candidate = store.observe(
        MemoryObservation("fact", "language", "Python", "run:1"), scope
    )
    assert store.recall("language", scope) == []

    store.transition(
        candidate["memory_id"],
        "verified",
        actor="human:alice",
        reason="confirmed",
        evidence_ref="evidence:1",
    )
    recalled = store.recall("language", scope)
    assert recalled[0]["memory_value"] == "Python"
    assert recalled[0]["why_retrieved"]["source_ref"] == "run:1"


def test_contradiction_supersession_and_expiry(tmp_path: Path) -> None:
    store = LongitudinalMemory(tmp_path / "memory.db")
    scope = MemoryScope("alice", project_id="atlas")
    first = store.observe(
        MemoryObservation("preference", "editor", "Vim", "run:1"), scope
    )
    store.transition(
        first["memory_id"],
        "verified",
        actor="human",
        reason="confirmed",
        evidence_ref="e:1",
    )
    second = store.observe(
        MemoryObservation(
            "preference",
            "editor",
            "Neovim",
            "run:2",
            expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        ),
        scope,
    )
    assert second["contradiction_detected"] is True
    store.transition(
        second["memory_id"],
        "verified",
        actor="human",
        reason="corrected",
        evidence_ref="e:2",
    )
    assert second["memory_id"] in store.expire()
    assert store.recall("editor", scope) == []


def test_session_isolation_and_decay(tmp_path: Path) -> None:
    store = LongitudinalMemory(tmp_path / "memory.db")
    first_scope = MemoryScope("alice", "session-a", "atlas", "work")
    second_scope = MemoryScope("alice", "session-b", "atlas", "work")
    observed = store.observe(
        MemoryObservation("fact", "draft", "session-a-only", "run:session-a"),
        first_scope,
    )
    store.transition(
        observed["memory_id"],
        "verified",
        actor="human",
        reason="session fact confirmed",
        evidence_ref="e:session",
    )
    assert store.recall("draft", second_scope) == []
    future = (datetime.now(UTC) + timedelta(days=365)).isoformat()
    decay = store.apply_decay(at=future, half_life_days=30, expiration_floor=0.2)
    assert decay[0]["status"] == "expired"
    assert store.recall("draft", first_scope) == []


def test_benchmark_meets_required_thresholds(tmp_path: Path) -> None:
    result = run_memory_longitudinal_benchmark(tmp_path)
    assert result["passed"] is True
    assert all(result["thresholds"].values())
    assert result["metrics"]["restore_fidelity"] == 1.0
    assert result["metrics"]["cross_user_contamination"] == 0.0

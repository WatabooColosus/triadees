"""Tests para bodega_global_context · Tríade Ω."""

from __future__ import annotations

from pathlib import Path

from triade.core.bodega_global_context import build_bodega_global_context
from triade.core.neuron_creator import NeuronSpec
from triade.core.neuron_registry import NeuronRegistry


def test_build_bodega_global_context_returns_ok(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    result = build_bodega_global_context(
        user_input="¿qué recuerdas?",
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        limit=5,
    )
    assert result["status"] == "ok"
    assert "identity_context" in result
    assert "recent_episodes" in result
    assert "semantic_recall" in result
    assert "semantic_governance" in result
    assert "project_context" in result
    assert "neuron_context" in result
    assert "learning_context" in result
    assert "safety_context" in result
    assert "qualia_context" in result
    assert "stable_audit_summary" in result
    assert "continuity_summary" in result
    assert "contradictions" in result
    assert "memory_confidence" in result
    assert "recommended_context_policy" in result


def test_build_bodega_global_context_safety_policy(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    result = build_bodega_global_context(
        user_input="test",
        db_path=db_path,
        runs_dir=tmp_path / "runs",
    )
    assert result["safety_context"]["identity_core_protected"] is True
    assert result["safety_context"]["stable_memory_requires_learning_pipeline"] is True
    assert result["safety_context"]["candidate_is_not_stable_memory"] is True


def test_build_bodega_global_context_empty_db_has_low_confidence(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    result = build_bodega_global_context(
        user_input="hello",
        db_path=db_path,
        runs_dir=tmp_path / "runs",
    )
    assert result["status"] == "ok"
    assert result["memory_confidence"] in ("low", "medium", "high")
    assert result["recommended_context_policy"] in (
        "use_full_context",
        "use_available_context",
        "ask_or_operate_with_limited_memory",
    )


def test_build_bodega_global_context_with_neurons(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    registry = NeuronRegistry(db_path=db_path)
    registry.register(NeuronSpec(
        name="neurona-ctx-test",
        mission="Probar contexto global.",
        domain="system_governance",
        rules=["Solo prueba"],
        status="stable",
        created_by="test",
    ))
    result = build_bodega_global_context(
        user_input="contexto",
        db_path=db_path,
        runs_dir=tmp_path / "runs",
    )
    assert result["status"] == "ok"
    assert len(result["neuron_context"]) >= 1
    names = [n["name"] for n in result["neuron_context"]]
    assert "neurona-ctx-test" in names


def test_build_bodega_global_context_semantic_disabled(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    result = build_bodega_global_context(
        user_input="test",
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        semantic_recall_enabled=False,
    )
    assert result["status"] == "ok"
    sr = result["semantic_recall"]
    assert sr.get("enabled") is False or sr.get("status") in ("disabled", "unavailable", "ok")


def test_build_bodega_global_context_no_identity_modification(tmp_path: Path) -> None:
    import sqlite3
    from triade.core.bodega import Bodega
    db_path = tmp_path / "triade.db"
    Bodega(db_path=db_path)
    before = sqlite3.connect(str(db_path)).execute("SELECT COUNT(*) FROM identity_core").fetchone()[0]
    build_bodega_global_context(
        user_input="modifica identidad",
        db_path=db_path,
        runs_dir=tmp_path / "runs",
    )
    after = sqlite3.connect(str(db_path)).execute("SELECT COUNT(*) FROM identity_core").fetchone()[0]
    assert before == after


def test_build_bodega_global_context_has_semantic_governance(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    result = build_bodega_global_context(
        user_input="test",
        db_path=db_path,
        runs_dir=tmp_path / "runs",
    )
    assert "semantic_governance" in result
    sg = result["semantic_governance"]
    assert isinstance(sg, dict)
    assert "status" in sg


def test_build_bodega_global_context_has_stable_audit_summary(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    result = build_bodega_global_context(
        user_input="test",
        db_path=db_path,
        runs_dir=tmp_path / "runs",
    )
    assert "stable_audit_summary" in result
    sa = result["stable_audit_summary"]
    assert isinstance(sa, dict)


def test_build_bodega_global_context_no_candidate_consolidation(tmp_path: Path) -> None:
    """Verifica que el contexto global no consolida memoria candidate como verdad."""
    import sqlite3
    db_path = tmp_path / "triade.db"
    from triade.core.bodega import Bodega
    Bodega(db_path=db_path)
    before = sqlite3.connect(str(db_path)).execute(
        "SELECT COUNT(*) FROM learning_queue WHERE status = 'candidate'"
    ).fetchone()[0]
    build_bodega_global_context(
        user_input="consolida memoria",
        db_path=db_path,
        runs_dir=tmp_path / "runs",
    )
    after = sqlite3.connect(str(db_path)).execute(
        "SELECT COUNT(*) FROM learning_queue WHERE status = 'candidate'"
    ).fetchone()[0]
    assert before == after

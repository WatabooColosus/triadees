"""Tests para neuron_mission_selector (DB-backed)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from triade.core.neuron_missions import NeuronMission, NeuronMissionStore
from triade.core.neuron_mission_selector import select_relevant_missions


def _make_store(tmp_path: Path) -> NeuronMissionStore:
    return NeuronMissionStore(db_path=tmp_path / "test.db")


def _seed_missions(store: NeuronMissionStore) -> list[int]:
    ids = []
    for title, mission, domain, status in [
        ("ML Training", "Train neural networks for classification", "ml", "candidate"),
        ("Data Pipeline", "Build ETL pipeline for analytics", "analytics", "experimental"),
        ("Cooking Bot", "Generate cooking recipes from ingredients", "cooking", "candidate"),
        ("Deprecated Mission", "Old unused mission", "ml", "paused"),
        ("Stable Monitor", "Monitor system health continuously", "ops", "stable"),
    ]:
        m = NeuronMission(neuron_id=1, title=title, mission=mission, domain=domain, status=status)
        ids.append(store.create_mission(m))
    return ids


def test_select_filters_by_domain():
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        _seed_missions(store)
        result = select_relevant_missions(domain="ml", db_path=Path(tmp) / "test.db", limit=10)
        assert result["status"] == "ok"
        assert all(m["domain"] == "ml" for m in result["selected"])
        assert len(result["selected"]) >= 1


def test_select_rejects_paused():
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        _seed_missions(store)
        result = select_relevant_missions(domain="ml", db_path=Path(tmp) / "test.db", limit=10)
        rejected_ids = {r["id"] for r in result["rejected"]}
        all_ids = {m["id"] for m in result["selected"]} | rejected_ids
        paused = [m for m in store.list_missions(limit=50) if m.status == "paused"]
        for pm in paused:
            assert pm.id in rejected_ids


def test_keyword_match_boosts_score():
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        _seed_missions(store)
        result = select_relevant_missions(
            user_input="neural network training classification",
            db_path=Path(tmp) / "test.db",
            limit=10,
        )
        assert result["count"] >= 1
        assert result["selected"][0]["title"] == "ML Training"


def test_limit_respected():
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        _seed_missions(store)
        result = select_relevant_missions(domain="ml", db_path=Path(tmp) / "test.db", limit=1)
        assert result["count"] <= 1


def test_empty_db():
    with tempfile.TemporaryDirectory() as tmp:
        result = select_relevant_missions(user_input="test", db_path=Path(tmp) / "test.db")
        assert result["status"] == "ok"
        assert result["count"] == 0
        assert result["selected"] == []


def test_policy_fields():
    with tempfile.TemporaryDirectory() as tmp:
        result = select_relevant_missions(db_path=Path(tmp) / "test.db")
        assert result["policy"]["no_identity_core_modification"] is True
        assert result["policy"]["selector_is_read_only"] is True


def test_selected_has_relevance_score():
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp))
        _seed_missions(store)
        result = select_relevant_missions(domain="ml", db_path=Path(tmp) / "test.db")
        for m in result["selected"]:
            assert "relevance_score" in m
            assert isinstance(m["relevance_score"], float)

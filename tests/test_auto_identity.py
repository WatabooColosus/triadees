"""Tests del auto-modelo dinámico (Fase F-02)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.memory.auto_identity_store import AutoIdentityStore


def make_auto_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(schema)
    return db_path


# ---------------------------------------------------------------------------
# AutoIdentityStore
# ---------------------------------------------------------------------------

def test_store_creates_table(tmp_path: Path) -> None:
    db_path = make_auto_db(tmp_path)
    store = AutoIdentityStore(db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "auto_identity" in tables


def test_add_trait(tmp_path: Path) -> None:
    db_path = make_auto_db(tmp_path)
    store = AutoIdentityStore(db_path=db_path)

    result = store.add_or_update("test_capability", "I am good at analysis", category="capability")
    assert result["updated"] is False
    assert result["confidence"] == 0.3
    assert result["evidence_count"] == 1

    traits = store.load_active()
    assert len(traits) == 1
    assert traits[0]["trait_key"] == "test_capability"
    assert traits[0]["status"] == "candidate"


def test_update_trait_increases_evidence(tmp_path: Path) -> None:
    db_path = make_auto_db(tmp_path)
    store = AutoIdentityStore(db_path=db_path)

    store.add_or_update("test_trait", "version 1", category="behavior")
    result = store.add_or_update("test_trait", "version 2", category="behavior")
    assert result["updated"] is True
    assert result["evidence_count"] == 2
    assert result["confidence"] == 0.35

    traits = store.load_active()
    assert len(traits) == 1
    assert traits[0]["trait_value"] == "version 2"


def test_archive_trait(tmp_path: Path) -> None:
    db_path = make_auto_db(tmp_path)
    store = AutoIdentityStore(db_path=db_path)

    store.add_or_update("archivable", "will be archived")
    assert store.archive("archivable") is True
    assert store.archive("archivable") is False  # already archived

    traits = store.load_active()
    assert len(traits) == 0


def test_promote_trait(tmp_path: Path) -> None:
    db_path = make_auto_db(tmp_path)
    store = AutoIdentityStore(db_path=db_path)

    store.add_or_update("promotable", "will be stable")
    assert store.promote("promotable") is True
    assert store.promote("promotable") is False  # already stable

    traits = store.load_active()
    assert traits[0]["status"] == "stable"


def test_load_by_category(tmp_path: Path) -> None:
    db_path = make_auto_db(tmp_path)
    store = AutoIdentityStore(db_path=db_path)

    store.add_or_update("cap_1", "analytical", category="capability")
    store.add_or_update("cap_2", "creative", category="capability")
    store.add_or_update("pref_1", "likes recursion", category="preference")

    capabilities = store.load_by_category("capability")
    assert len(capabilities) == 2

    preferences = store.load_by_category("preference")
    assert len(preferences) == 1


def test_doctor(tmp_path: Path) -> None:
    db_path = make_auto_db(tmp_path)
    store = AutoIdentityStore(db_path=db_path)

    report = store.doctor()
    assert report["status"] == "ok"
    assert report["active_count"] == 0

    store.add_or_update("trait_a", "value a", category="capability")
    store.add_or_update("trait_b", "value b", category="preference")

    report = store.doctor()
    assert report["active_count"] == 2
    assert report["categories"]["capability"] == 1
    assert report["categories"]["preference"] == 1


# ---------------------------------------------------------------------------
# Evolve from reflection
# ---------------------------------------------------------------------------

def test_evolve_from_reflection_creates_traits(tmp_path: Path) -> None:
    db_path = make_auto_db(tmp_path)
    store = AutoIdentityStore(db_path=db_path)

    reflection = {
        "observations": [
            {"observation": "Tríade muestra capacidad para análisis profundo de código"},
        ],
        "learning_candidates": {
            "candidate_themes": [
                {"theme": "El sistema responde mejor cuando hay contexto de memoria"},
            ],
        },
    }

    evolved = store.evolve_from_reflection("run-evolve-1", reflection)
    assert len(evolved) == 2

    traits = store.load_active()
    assert len(traits) == 2

    # Verify categories
    observed = [t for t in traits if t["category"] == "observed_pattern"]
    themes = [t for t in traits if t["category"] == "discovered_mission"]
    assert len(observed) == 1
    assert len(themes) == 1


def test_evolve_from_reflection_skips_short_observations(tmp_path: Path) -> None:
    db_path = make_auto_db(tmp_path)
    store = AutoIdentityStore(db_path=db_path)

    reflection = {
        "observations": [{"observation": "corto"}],
        "learning_candidates": {"candidate_themes": []},
    }

    evolved = store.evolve_from_reflection("run-short", reflection)
    assert len(evolved) == 0


def test_evolve_from_reflection_integrates_with_bodega(tmp_path: Path) -> None:
    from triade.core.bodega import Bodega

    db_path = make_auto_db(tmp_path)
    bodega = Bodega(db_path=db_path)

    # Add a run first
    from triade.core.contracts import InputPacket
    packet = InputPacket(user_input="test identity evolution", run_id="run-identity-1")
    bodega.create_run(packet)

    store = bodega.auto_identity_store
    store.add_or_update("learned_trait", "I learn from experience", category="capability")

    identity = bodega._fetch_identity()
    assert len(identity) >= 6  # 6 core + at least 0 auto

    # Now check recall includes auto traits
    memory = bodega.recall(packet)
    auto_traits_in_recall = [m for m in memory.identity_matches if m.get("source") == "auto_identity"]
    assert len(auto_traits_in_recall) == 1
    assert auto_traits_in_recall[0]["key"] == "learned_trait"

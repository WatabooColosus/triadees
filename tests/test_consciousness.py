"""Tests para Fase G: Atención y memoria de trabajo (G-01, G-02, G-03)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.consciousness import FocusModulator, SalienceEngine, WorkingMemory


# ── G-01: SalienceEngine ─────────────────────────────────────────────────────


class TestSalienceEngine:
    def test_score_returns_vector(self) -> None:
        engine = SalienceEngine(db_path=":memory:")
        sv = engine.score("Hola", "conversation", "low", "low", "constructive")
        assert 0.0 <= sv.relevance <= 1.0
        assert 0.0 <= sv.emotional_salience <= 1.0
        assert 0.0 <= sv.goal_salience <= 1.0
        assert 0.0 <= sv.novelty_salience <= 1.0
        assert 0.0 <= sv.urgency_salience <= 1.0

    def test_high_urgency_increases_salience(self) -> None:
        engine = SalienceEngine(db_path=":memory:")
        low = engine.score("test", "conversation", "low", "low", "constructive")
        high = engine.score("test", "conversation", "high", "critical", "constructive")
        assert high.relevance >= low.relevance

    def test_same_input_lowers_novelty(self, tmp_path: Path) -> None:
        db_path = tmp_path / "triade.db"
        schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
        with sqlite3.connect(db_path) as conn:
            conn.executescript(schema)
            conn.execute(
                "INSERT INTO runs (run_id, source, user_input, status, created_at) VALUES (?, ?, ?, ?, ?)",
                ("r1", "test", "hola mundo", "ok", "2026-06-10"),
            )
            conn.execute(
                "INSERT INTO runs (run_id, source, user_input, status, created_at) VALUES (?, ?, ?, ?, ?)",
                ("r2", "test", "hola mundo", "ok", "2026-06-10"),
            )
        engine = SalienceEngine(db_path=db_path)
        sv = engine.score("hola mundo", "conversation", "low", "low", "constructive")
        assert sv.novelty_salience < 0.5

    def test_new_input_has_high_novelty(self, tmp_path: Path) -> None:
        db_path = tmp_path / "triade.db"
        schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
        with sqlite3.connect(db_path) as conn:
            conn.executescript(schema)
        engine = SalienceEngine(db_path=db_path)
        sv = engine.score("algo completamente nuevo", "conversation", "low", "low", "constructive")
        assert sv.novelty_salience >= 0.5

    def test_emotional_salience_uses_tone(self) -> None:
        engine = SalienceEngine(db_path=":memory:")
        neutral = engine.score("test", "conversation", "low", "low", "constructive")
        cautious = engine.score("test", "conversation", "low", "low", "cautious")
        assert cautious.emotional_salience >= neutral.emotional_salience

    def test_goal_salience_with_active_goals(self, tmp_path: Path) -> None:
        db_path = tmp_path / "triade.db"
        schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
        with sqlite3.connect(db_path) as conn:
            conn.executescript(schema)
            conn.execute(
                "INSERT INTO goals (title, description, status) VALUES (?, ?, ?)",
                ("memoria", "mejorar la memoria semantica", "active"),
            )
        engine = SalienceEngine(db_path=db_path)
        sv = engine.score("hay que mejorar la memoria", "conversation", "low", "low", "constructive")
        assert sv.goal_salience > 0.2

    def test_goal_salience_no_active_goals(self) -> None:
        engine = SalienceEngine(db_path=":memory:")
        sv = engine.score("test", "conversation", "low", "low", "constructive")
        assert sv.goal_salience <= 0.2

    def test_doctor(self) -> None:
        engine = SalienceEngine(db_path=":memory:")
        report = engine.doctor()
        assert report["status"] == "ok"
        assert "weights" in report


# ── G-02: WorkingMemory ──────────────────────────────────────────────────────


class TestWorkingMemory:
    def test_push_and_peek(self) -> None:
        wm = WorkingMemory(max_size=5)
        assert len(wm.peek()) == 0
        sal = SalienceEngine(db_path=":memory:").score("hola", "conversation", "low", "low", "constructive")
        wm.push("hola mundo", "user", sal)
        assert len(wm.peek()) == 1

    def test_prune_evicts_lowest_salience(self) -> None:
        wm = WorkingMemory(max_size=3)
        # Manually create items with clearly different salience
        from triade.consciousness.salience import SalienceVector
        wm.push("importante", "user", SalienceVector(relevance=0.9, urgency_salience=0.9))
        wm.push("medio", "user", SalienceVector(relevance=0.5, urgency_salience=0.5))
        wm.push("bajo", "user", SalienceVector(relevance=0.2, urgency_salience=0.2))
        wm.push("muy bajo", "user", SalienceVector(relevance=0.1, urgency_salience=0.1))
        assert len(wm.peek()) == 3
        texts = [it.text for it in wm.peek()]
        assert "importante" in texts
        assert "muy bajo" not in texts

    def test_get_relevant_returns_sorted(self) -> None:
        wm = WorkingMemory(max_size=10)
        engine = SalienceEngine(db_path=":memory:")
        for text, urgency in [("bajo", "low"), ("alto", "high"), ("medio", "medium")]:
            sal = engine.score(text, "conversation", urgency, "low", "constructive")
            wm.push(text, "user", sal)
        relevant = wm.get_relevant(min_relevance=0.0, limit=3)
        assert len(relevant) == 3
        assert relevant[0].salience.relevance >= relevant[-1].salience.relevance

    def test_get_relevant_filters_by_min_relevance(self) -> None:
        wm = WorkingMemory(max_size=10)
        engine = SalienceEngine(db_path=":memory:")
        for text, urgency in [("bajo", "low"), ("alto", "high")]:
            sal = engine.score(text, "conversation", urgency, "low", "constructive")
            wm.push(text, "user", sal)
        filtered = wm.get_relevant(min_relevance=0.5, limit=5)
        for item in filtered:
            assert item.salience.relevance >= 0.5

    def test_clear_empties(self) -> None:
        wm = WorkingMemory(max_size=5)
        sal = SalienceEngine(db_path=":memory:").score("test", "conversation", "low", "low", "constructive")
        wm.push("test", "user", sal)
        wm.clear()
        assert len(wm.peek()) == 0

    def test_get_context_includes_labels(self) -> None:
        wm = WorkingMemory(max_size=5)
        sal = SalienceEngine(db_path=":memory:").score("test", "conversation", "low", "low", "constructive")
        wm.push("contenido de prueba", "user", sal)
        ctx = wm.get_context()
        assert "User" in ctx
        assert "contenido de prueba" in ctx

    def test_access_count_increments(self) -> None:
        wm = WorkingMemory(max_size=5)
        sal = SalienceEngine(db_path=":memory:").score("test", "conversation", "low", "low", "constructive")
        wm.push("item", "user", sal)
        before = wm.peek()[0].access_count
        wm.get_relevant(limit=5)
        assert wm.peek()[0].access_count > before

    def test_doctor(self) -> None:
        wm = WorkingMemory(max_size=5)
        sal = SalienceEngine(db_path=":memory:").score("test", "conversation", "low", "low", "constructive")
        wm.push("test", "user", sal)
        report = wm.doctor()
        assert report["status"] == "ok"
        assert report["size"] == 1
        assert report["max_size"] == 5


# ── G-03: FocusModulator ─────────────────────────────────────────────────────


class TestFocusModulator:
    def test_threshold_with_no_mood_returns_base(self) -> None:
        mod = FocusModulator(db_path=":memory:")
        thr = mod.threshold()
        assert thr == mod.BASE_THRESHOLD

    def test_high_fatigue_raises_threshold(self, tmp_path: Path) -> None:
        db_path = tmp_path / "triade.db"
        schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
        with sqlite3.connect(db_path) as conn:
            conn.executescript(schema)
            conn.execute(
                "INSERT INTO runs (run_id, source, user_input, status, created_at) VALUES (?, ?, ?, ?, ?)",
                ("r1", "test", "input", "ok", "2026-06-10"),
            )
            conn.execute(
                "INSERT INTO hypothalamus_state (run_id, mood_valence, mood_arousal, fatigue, primary_emotion) "
                "VALUES (?, ?, ?, ?, ?)",
                ("r1", 0.3, 0.2, 0.9, "fatigued"),
            )
        mod = FocusModulator(db_path=db_path)
        thr = mod.threshold()
        assert thr > mod.BASE_THRESHOLD

    def test_positive_mood_lowers_threshold(self, tmp_path: Path) -> None:
        db_path = tmp_path / "triade.db"
        schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
        with sqlite3.connect(db_path) as conn:
            conn.executescript(schema)
            conn.execute(
                "INSERT INTO runs (run_id, source, user_input, status, created_at) VALUES (?, ?, ?, ?, ?)",
                ("r1", "test", "input", "ok", "2026-06-10"),
            )
            conn.execute(
                "INSERT INTO hypothalamus_state (run_id, mood_valence, mood_arousal, fatigue, primary_emotion) "
                "VALUES (?, ?, ?, ?, ?)",
                ("r1", 0.8, 0.7, 0.1, "engaged"),
            )
        mod = FocusModulator(db_path=db_path)
        thr = mod.threshold()
        assert thr < mod.BASE_THRESHOLD

    def test_threshold_bounds(self) -> None:
        mod = FocusModulator(db_path=":memory:")
        thr = mod.threshold()
        assert mod.MIN_THRESHOLD <= thr <= mod.MAX_THRESHOLD

    def test_should_filter(self) -> None:
        mod = FocusModulator(db_path=":memory:")
        base = mod.threshold()
        assert mod.should_filter(base - 0.1) is True
        assert mod.should_filter(base + 0.1) is False

    def test_doctor(self) -> None:
        mod = FocusModulator(db_path=":memory:")
        report = mod.doctor()
        assert report["status"] == "ok"
        assert "current_threshold" in report

"""Tests del estado emocional persistente del Hipotálamo (Fase F-01)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from triade.core.contracts import InputPacket, SignalPacket
from triade.core.hypothalamus import Hypothalamus
from triade.memory.hypothalamus_store import (
    HypothalamusStateStore,
    EmotionalState,
    compute_primary_emotion,
    fatigue_decay,
    mood_from_signals,
)


def make_state_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
        conn.execute(
            "INSERT INTO runs (run_id, source, user_input, status) VALUES (?, ?, ?, ?)",
            ("pre-state-run", "test", "inicialización previa", "ok"),
        )
    return db_path


def add_run(db_path: Path, run_id: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs (run_id, source, user_input, status) VALUES (?, ?, ?, ?)",
            (run_id, "test", "test input", "created"),
        )


def make_signal(run_id: str, **overrides: object) -> SignalPacket:
    return SignalPacket(
        run_id=run_id,
        intent=str(overrides.get("intent", "conversation")),
        tone=str(overrides.get("tone", "constructive")),
        urgency=str(overrides.get("urgency", "medium")),
        risk=str(overrides.get("risk", "low")),
        pv7=dict(overrides.get("pv7", {
            "humildad": 0.7, "generosidad": 0.7, "respeto": 0.8,
            "paciencia": 0.7, "templanza": 0.7, "caridad": 0.7, "diligencia": 0.8,
        })),
        notes=list(overrides.get("notes", ["test"])),
    )


# ---------------------------------------------------------------------------
# HypothalamusStateStore
# ---------------------------------------------------------------------------

def test_store_initialize_creates_table(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "hypothalamus_state" in tables


def test_store_save_and_load(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    run_id = "test-run-1"
    add_run(db_path, run_id)

    signals = make_signal(run_id, tone="constructive", urgency="medium", risk="low")
    row_id = store.save(run_id, signals)
    assert row_id > 0

    state = store.load_latest()
    assert state is not None
    assert state.valence > 0
    assert state.run_count == 1
    assert state.primary_emotion in ("neutral", "positive")


def test_store_load_latest_returns_most_recent(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    for i in range(3):
        rid = f"run-{i}"
        add_run(db_path, rid)
        signals = make_signal(rid, tone="constructive", urgency="low", risk="low")
        store.save(rid, signals)

    state = store.load_latest()
    assert state is not None
    assert state.run_count == 3


def test_store_load_latest_empty(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    assert store.load_latest() is None


def test_store_fatigue_increases_with_runs(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    for i in range(5):
        rid = f"fatigue-run-{i}"
        add_run(db_path, rid)
        store.save(rid, make_signal(rid))

    state = store.load_latest()
    assert state is not None
    expected = round(5 * 0.05, 4)
    assert state.fatigue == expected


def test_store_update_fatigue(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    rid = "fatigue-update"
    add_run(db_path, rid)
    store.save(rid, make_signal(rid))

    store.update_fatigue(0.1)
    state = store.load_latest()
    assert state is not None
    assert state.fatigue == 0.1


def test_store_update_fatigue_no_state(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    assert store.update_fatigue(0.1) is False


def test_store_doctor(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    report = store.doctor()
    assert report["status"] == "ok"
    assert report["count"] == 0
    assert report["latest"] is None

    rid = "doctor-run"
    add_run(db_path, rid)
    store.save(rid, make_signal(rid))

    report = store.doctor()
    assert report["count"] == 1
    assert report["latest"] is not None
    assert report["latest"]["run_count"] == 1


# ---------------------------------------------------------------------------
# EmotionalState helpers
# ---------------------------------------------------------------------------

def test_compute_primary_emotion() -> None:
    assert compute_primary_emotion(0.0, 0.0, 0.0) == "neutral"
    assert compute_primary_emotion(0.5, 0.6, 0.0) == "engaged"
    assert compute_primary_emotion(-0.5, 0.6, 0.0) == "anxious"
    assert compute_primary_emotion(0.5, -0.4, 0.0) == "calm"
    assert compute_primary_emotion(-0.5, -0.4, 0.0) == "withdrawn"
    assert compute_primary_emotion(0.4, 0.0, 0.0) == "positive"
    assert compute_primary_emotion(-0.4, 0.0, 0.0) == "cautious"
    assert compute_primary_emotion(0.0, 0.0, 0.8) == "fatigued"


def test_fatigue_decay() -> None:
    assert fatigue_decay(1.0, 60.0) == 1.0 - 0.01
    assert fatigue_decay(1.0, 600.0) == 1.0 - 0.1
    assert fatigue_decay(0.5, 120.0) == 0.5 - 0.02
    assert fatigue_decay(0.005, 60.0) == 0.0
    assert fatigue_decay(0.0, 60.0) == 0.0


def test_mood_from_signals_first_run() -> None:
    signals = make_signal("mood-1", tone="constructive", urgency="low", risk="low")
    mood = mood_from_signals(signals)
    assert mood.run_count == 1
    assert mood.fatigue == 0.05
    assert mood.last_active_at is not None


def test_mood_from_signals_with_previous() -> None:
    prev = EmotionalState(fatigue=0.5, run_count=5)
    signals = make_signal("mood-2", tone="urgent", urgency="high", risk="critical")
    mood = mood_from_signals(signals, previous=prev)
    assert mood.run_count == 6
    assert mood.fatigue > 0.5
    assert mood.arousal > 0
    assert mood.dominance < 0


# ---------------------------------------------------------------------------
# Hypothalamus integration
# ---------------------------------------------------------------------------

def test_hypothalamus_creates_emotional_state_on_analyze(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    hyp = Hypothalamus(state_store=store)

    packet = InputPacket(user_input="Hola, ¿cómo estás?", run_id="test-mood-1")
    add_run(db_path, packet.run_id)
    signals = hyp.analyze(packet)
    assert signals is not None
    assert signals.intent == "conversation"

    state = store.load_latest()
    assert state is not None
    assert state.run_count == 1
    assert state.fatigue > 0


def test_hypothalamus_mood_property(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    hyp = Hypothalamus(state_store=store)

    assert hyp.mood is None

    packet = InputPacket(user_input="Primera interacción", run_id="mood-prop-1")
    add_run(db_path, packet.run_id)
    hyp.analyze(packet)

    mood = hyp.mood
    assert mood is not None
    assert mood.run_count >= 1


def test_hypothalamus_mood_modulates_tone_when_fatigued(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    hyp = Hypothalamus(state_store=store)

    fake_rid = "fatigue-base"
    add_run(db_path, fake_rid)
    store.save_raw(fake_rid, EmotionalState(fatigue=0.8, primary_emotion="fatigued", run_count=10))

    packet = InputPacket(user_input="Hazme una tarea", run_id="fatigue-test-1")
    add_run(db_path, packet.run_id)
    signals = hyp.analyze(packet)
    assert signals.tone == "cautious"


def test_hypothalamus_mood_modulates_pv7(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    hyp = Hypothalamus(state_store=store)

    fake_rid = "pv7-base"
    add_run(db_path, fake_rid)
    store.save_raw(fake_rid, EmotionalState(fatigue=0.8, primary_emotion="fatigued", run_count=5))

    packet = InputPacket(user_input="Construye un módulo", run_id="pv7-test-1")
    add_run(db_path, packet.run_id)
    signals = hyp.analyze(packet)

    base = 0.8
    fatigued_factor = 0.85
    assert signals.pv7["diligencia"] == round(min(1.0, base * fatigued_factor), 4)


def test_hypothalamus_without_store_works_as_before() -> None:
    hyp = Hypothalamus()
    packet = InputPacket(user_input="Prueba sin store")
    signals = hyp.analyze(packet)
    assert signals.intent == "conversation"
    assert hyp.mood is None


def test_hypothalamus_with_model_client(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.ok = True
    mock_result.text = '{"intent": "conversation", "tone": "positive", "urgency": "low", "risk": "low", "pv7": {"humildad": 0.8, "generosidad": 0.8, "respeto": 0.9, "paciencia": 0.8, "templanza": 0.8, "caridad": 0.8, "diligencia": 0.9}}'
    mock_result.error = None
    mock_client.generate.return_value = mock_result

    hyp = Hypothalamus(model_client=mock_client, state_store=store)
    packet = InputPacket(user_input="Hola", run_id="model-mood-1")
    add_run(db_path, packet.run_id)
    signals = hyp.analyze(packet)
    assert signals.tone == "positive"

    state = store.load_latest()
    assert state is not None
    assert state.run_count == 1


# ---------------------------------------------------------------------------
# LifePulse emotional integration
# ---------------------------------------------------------------------------

def test_life_pulse_snapshot_includes_emotional_state(tmp_path: Path) -> None:
    from triade.core.life_pulse import LifePulseEngine

    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    rid = "life-emotion"
    add_run(db_path, rid)
    store.save(rid, make_signal(rid, tone="constructive", urgency="medium", risk="low"))

    engine = LifePulseEngine(db_path=db_path, runs_dir=tmp_path / "runs", interval_seconds=5, reflection_limit=10)
    payload = engine.tick()

    assert "emotional_state" in payload
    assert payload["emotional_state"]["status"] == "ok"
    assert payload["emotional_state"]["count"] >= 1
    assert payload["emotional_state"]["latest"] is not None
    assert "valence" in payload["emotional_state"]["latest"]


def test_emotional_rest_decays_fatigue(tmp_path: Path) -> None:
    from triade.core.life_pulse import LifePulseEngine

    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    rid = "rest-test"
    add_run(db_path, rid)
    store.save_raw(rid, EmotionalState(fatigue=0.5, run_count=10))

    engine = LifePulseEngine(db_path=db_path, runs_dir=tmp_path / "runs", interval_seconds=60, reflection_limit=10)
    engine._update_emotional_rest()

    state = store.load_latest()
    assert state is not None
    assert state.fatigue < 0.5


# ---------------------------------------------------------------------------
# Reinforcement learning
# ---------------------------------------------------------------------------

def _setup_reinforce(store: HypothalamusStateStore, db_path: Path, rid: str) -> None:
    """Ensure run exists for reinforce to not violate FK."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO runs (run_id, source, user_input, status) VALUES (?, ?, ?, ?)",
            (rid, "test", "reinforce test", "created"),
        )


def test_reinforce_increases_valence_on_high_reward(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    rid = "reinforce-1"
    add_run(db_path, rid)
    store.save(rid, make_signal(rid, tone="constructive", urgency="medium", risk="low"))

    before = store.load_latest()
    assert before is not None
    bv = before.valence

    rid2 = "reinforce-2"
    _setup_reinforce(store, db_path, rid2)
    reinforced = store.reinforce(rid2, reward=0.8, hypothalamus_quality=0.9, central_quality=0.85, coherence_score=0.8)
    assert reinforced is not None
    assert reinforced.valence > bv
    assert reinforced.fatigue < before.fatigue


def test_reinforce_decreases_valence_on_low_reward(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    rid = "reinforce-neg-1"
    add_run(db_path, rid)
    store.save(rid, make_signal(rid, tone="constructive", urgency="medium", risk="low"))

    before = store.load_latest()
    assert before is not None
    bv = before.valence

    rid2 = "reinforce-neg-2"
    _setup_reinforce(store, db_path, rid2)
    reinforced = store.reinforce(rid2, reward=-0.5)
    assert reinforced is not None
    assert reinforced.valence < bv


def test_reinforce_no_state_returns_none(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    assert store.reinforce("no-state-run", reward=0.5) is None


def test_reinforcement_history(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    rid = "hist-1"
    add_run(db_path, rid)
    store.save(rid, make_signal(rid))

    for r in ("hist-2", "hist-3"):
        _setup_reinforce(store, db_path, r)
        store.reinforce(r, reward=0.6 if r == "hist-2" else 0.3)

    history = store.reinforcement_history()
    assert len(history) >= 2
    assert all("reward" in h for h in history)


def test_avg_reward(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    rid = "avg-1"
    add_run(db_path, rid)
    store.save(rid, make_signal(rid))

    for r in ("avg-2", "avg-3"):
        _setup_reinforce(store, db_path, r)
        store.reinforce(r, reward=0.8 if r == "avg-2" else 0.4)

    avg = store.avg_reward(10)
    assert avg == 0.6


def test_doctor_includes_reinforcement(tmp_path: Path) -> None:
    db_path = make_state_db(tmp_path)
    store = HypothalamusStateStore(db_path=db_path)
    rid = "dr-1"
    add_run(db_path, rid)
    store.save(rid, make_signal(rid))

    rid2 = "dr-2"
    _setup_reinforce(store, db_path, rid2)
    store.reinforce(rid2, reward=0.5)

    report = store.doctor()
    assert "reinforcement" in report
    assert report["reinforcement"]["events"] >= 1

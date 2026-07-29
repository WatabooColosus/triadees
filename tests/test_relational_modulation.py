from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.memory.relational_modulation import RelationalModulationStore


def test_sessions_and_users_are_isolated(tmp_path: Path) -> None:
    store = RelationalModulationStore(tmp_path / "state.db")
    event = store.apply_event(
        "alice",
        "session-a",
        "user_correction",
        {"paciencia": 0.08},
        source_ref="run:1",
        explanation="A correction requests more deliberation.",
    )
    assert store.get("alice", "session-a")["pv7"] == event["after"]
    assert store.get("alice", "session-b")["pv7"] != event["after"]
    assert store.get("bob", "session-a")["pv7"] != event["after"]


def test_event_decay_limits_and_explanation(tmp_path: Path) -> None:
    store = RelationalModulationStore(tmp_path / "state.db")
    first = store.apply_event(
        "alice",
        "s1",
        "conflict_signal",
        {"templanza": -5.0, "paciencia": 5.0},
        source_ref="run:conflict",
        explanation="Conflict signal bounded by the relational policy.",
    )
    assert first["after"]["templanza"] >= first["before"]["templanza"] - 0.12
    assert first["after"]["paciencia"] <= first["before"]["paciencia"] + 0.12
    decay = store.decay("alice", "s1", elapsed_seconds=3600, half_life_seconds=3600)
    assert abs(decay["after"]["templanza"] - 0.7) < abs(
        first["after"]["templanza"] - 0.7
    )
    assert "baseline" in decay["explanation"]


def test_rollback_restart_restore_and_identity_invariance(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    store = RelationalModulationStore(db_path)
    with sqlite3.connect(db_path) as conn:
        identity_before = conn.execute(
            "SELECT key, value FROM identity_core ORDER BY key"
        ).fetchall()
    before = store.get("alice", "s1")["pv7"]
    event = store.apply_event(
        "alice",
        "s1",
        "task_success",
        {"diligencia": 0.05},
        source_ref="task:1",
        explanation="Verified task outcome.",
    )
    restarted = RelationalModulationStore(db_path)
    assert restarted.get("alice", "s1")["pv7"] == event["after"]
    rollback = restarted.rollback_event(
        event["event_id"], actor="human:test", reason="recovery exercise"
    )
    assert rollback["restored"] == before
    with sqlite3.connect(db_path) as conn:
        identity_after = conn.execute(
            "SELECT key, value FROM identity_core ORDER BY key"
        ).fetchall()
    assert identity_after == identity_before

    backup = restarted.backup(tmp_path / "backup" / "state.db")
    restore = RelationalModulationStore.restore_to_sandbox(
        backup["path"], tmp_path / "restore" / "state.db", backup["fingerprint"]
    )
    assert restore["status"] == "verified"
    assert restore["production_overwritten"] is False


def test_state_never_claims_subjective_emotion(tmp_path: Path) -> None:
    state = RelationalModulationStore(tmp_path / "state.db").get("alice", "s1")
    assert state["state_type"] == "relational modulation state"
    assert state["subjective_emotion_claimed"] is False


def test_hypothalamus_uses_session_scoped_relational_state(tmp_path: Path) -> None:
    from triade.core.contracts import InputPacket
    from triade.core.hypothalamus import Hypothalamus

    db_path = tmp_path / "state.db"
    store = RelationalModulationStore(db_path)
    store.apply_event(
        "alice",
        "session-a",
        "user_correction",
        {"paciencia": 0.1},
        source_ref="run:correction",
        explanation="Correction requests patience.",
    )
    hyp = Hypothalamus(model_client=None, db_path=str(db_path))
    alice = hyp.analyze(
        InputPacket(
            "Analiza esto",
            context={"user_id": "alice", "session_id": "session-a"},
        )
    )
    bob = hyp.analyze(
        InputPacket(
            "Analiza esto",
            context={"user_id": "bob", "session_id": "session-a"},
        )
    )
    assert alice.pv7["paciencia"] > bob.pv7["paciencia"]
    assert any("no subjective emotion claim" in note for note in alice.notes)

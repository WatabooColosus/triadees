from pathlib import Path

from triade.memory.user_profile_store import UserProfileStore


def test_explicit_name_persists_and_is_scoped(tmp_path: Path) -> None:
    store = UserProfileStore(tmp_path / "triade.db")

    captured = store.capture("browser:session-a", "Mucho gusto, me llamo santiago.", "run-1")

    assert captured["stored"] is True
    assert store.load("browser:session-a") == {"preferred_name": "Santiago"}
    assert store.load("browser:session-b") == {}


def test_repeated_fact_reinforces_without_duplicate(tmp_path: Path) -> None:
    store = UserProfileStore(tmp_path / "triade.db")
    store.capture("browser:session-a", "Mi nombre es Santiago", "run-1")
    store.capture("browser:session-a", "me llamo Santiago", "run-2")

    with store._connect() as conn:
        row = conn.execute(
            "SELECT fact_value, evidence_count FROM user_profile_memory WHERE principal_id = ?",
            ("browser:session-a",),
        ).fetchone()
    assert dict(row) == {"fact_value": "Santiago", "evidence_count": 2}


def test_unscoped_or_implicit_text_is_not_stored(tmp_path: Path) -> None:
    store = UserProfileStore(tmp_path / "triade.db")

    assert store.capture(None, "me llamo Santiago", "run-1")["stored"] is False
    assert store.capture("browser:session-a", "Santiago es una ciudad", "run-2")["stored"] is False

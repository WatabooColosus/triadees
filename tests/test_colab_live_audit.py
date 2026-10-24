"""Colab telemetry tests: isolated SQLite fixtures, no real Drive/network."""

from __future__ import annotations

import json
import sqlite3
import urllib.error
from pathlib import Path

from tools import colab_live_audit as audit


def test_missing_db_is_explicit(tmp_path: Path) -> None:
    assert audit._database(tmp_path / "not-here.db") == {"present": False}


def test_db_counts_do_not_export_user_data(tmp_path: Path) -> None:
    db = tmp_path / "synthetic.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE autonomous_tasks(status TEXT, prompt TEXT)")
        conn.execute(
            "INSERT INTO autonomous_tasks VALUES (?, ?)",
            ("completed", "PRIVATE PROMPT"),
        )
        conn.execute("CREATE TABLE auth_users(email TEXT, password_hash TEXT)")
        conn.execute(
            "INSERT INTO auth_users VALUES (?, ?)",
            ("private@example.org", "PRIVATE HASH"),
        )
    result = audit._database(db)
    assert result["quick_check"] == "ok"
    assert result["task_statuses"] == {"completed": 1}
    assert result["tables"]["auth_users"] == 1
    output = json.dumps(result)
    assert "PRIVATE" not in output and "example.org" not in output


def test_http_protected_is_not_service_down(monkeypatch) -> None:
    def forbidden(_url: str, timeout: int):
        raise urllib.error.HTTPError("", 403, "denied", {}, None)

    monkeypatch.setattr(audit.urllib.request, "urlopen", forbidden)
    assert audit._local_http("/health/deep") == {
        "http": 403,
        "protected": True,
    }


def test_atomic_file_and_longitudinal_deltas(tmp_path: Path, monkeypatch) -> None:
    samples = iter(
        [
            {
                "schema": "triade-live-audit-v2",
                "captured_at_utc": "first",
                "database": {"tables": {"worker_events": 7}},
            },
            {
                "schema": "triade-live-audit-v2",
                "captured_at_utc": "second",
                "database": {"tables": {"worker_events": 12}},
            },
        ]
    )
    monkeypatch.setattr(audit, "capture", lambda *args, **kwargs: next(samples))
    audit.publish_once(tmp_path)
    new = audit.publish_once(tmp_path)
    assert new["comparison"]["counter_deltas"] == {"worker_events": 5}
    assert json.loads((tmp_path / "triade-live-latest.json").read_text()) == new
    assert not list(tmp_path.glob("*.tmp"))


def test_monitor_duplicate_call_and_stop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        audit,
        "capture",
        lambda *args, **kwargs: {
            "schema": "triade-live-audit-v2",
            "captured_at_utc": "test",
            "source_git_sha": "a" * 40,
            "services": {"ollama": {"ok": True}},
            "database": {"tables": {}},
        },
    )
    first = audit.start_monitor(tmp_path)
    second = audit.start_monitor(tmp_path)
    assert first["status"] == "active"
    assert second["status"] == "already_active"
    assert audit.stop_monitor() is True
    assert audit.stop_monitor() is False


def test_no_false_boolean_delta() -> None:
    counters = {"worker_events": 0, "not_a_count": True, "missing": None}
    assert audit._counters({"database": {"tables": counters}}) == {"worker_events": 0}

import sqlite3
from pathlib import Path

import pytest

from triade.validation.runtime_long_run import run_wall_clock_validation


def test_duration_is_real_and_not_compressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "db"
    sqlite3.connect(db).close()
    monkeypatch.setattr("triade.validation.runtime_long_run._http_ok", lambda _: True)
    report = run_wall_clock_validation(
        duration_seconds=1, interval_seconds=1, db_path=db, web_url="w", ollama_url="o"
    )
    assert report["elapsed_seconds"] >= 1
    assert report["wall_clock_not_compressed"] is True
    assert report["availability"] == 1.0
    assert report["metrics"]["duplicate_effects"] == 0
    assert report["metrics"]["lost_tasks"] == 0
    assert report["metrics"]["false_completed"] == 0
    assert report["metrics"]["late_results_accepted"] == 0
    assert report["metrics"]["artifact_loss"] == 0
    assert report["metrics"]["rollback_success_percent"] == 100.0


def test_invalid_zero_duration_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        run_wall_clock_validation(
            duration_seconds=0,
            interval_seconds=1,
            db_path=tmp_path / "db",
            web_url="w",
            ollama_url="o",
        )


def test_false_completion_and_duplicate_effects_fail_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE autonomous_tasks("
            "task_id TEXT,idempotency_key TEXT,status TEXT,result_ref TEXT)"
        )
        conn.execute("INSERT INTO autonomous_tasks VALUES('a','same','completed',NULL)")
        conn.execute(
            "INSERT INTO autonomous_tasks VALUES('b','same','completed','missing')"
        )
    monkeypatch.setattr("triade.validation.runtime_long_run._http_ok", lambda _: True)

    report = run_wall_clock_validation(
        duration_seconds=1, interval_seconds=1, db_path=db, web_url="w", ollama_url="o"
    )

    assert report["metrics"]["duplicate_effects"] == 1
    assert report["metrics"]["false_completed"] == 2
    assert report["metrics"]["artifact_loss"] == 2
    assert report["passed"] is False

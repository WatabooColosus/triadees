import sqlite3

import pytest

from scripts import audit_autonomy_gates as module


def test_audit_never_creates_missing_database(tmp_path):
    db = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        module.audit(db, "http://127.0.0.1:1")
    assert not db.exists()


def test_rows_and_workers_do_not_prove_causality_or_scheduler(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE learning_queue(status TEXT, run_use_count INTEGER)")
        conn.execute("INSERT INTO learning_queue VALUES('evidence_verified', 100)")
        conn.execute(
            "CREATE TABLE improvement_canaries(status TEXT, payload_json TEXT)"
        )
        conn.execute("INSERT INTO improvement_canaries VALUES('completed', '{}')")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        module, "_http", lambda url: {"status": 200, "body": {"workers_active": True}}
    )
    gates = {g["gate"]: g for g in module.audit(db, "http://local")["gates"]}
    for name in (
        "scheduler_live",
        "causal_production_use",
        "error_recovery",
        "improvement_canary",
        "independent_learning_evidence",
    ):
        assert gates[name]["status"] == "PENDING"
    assert gates["database_integrity"]["status"] == "PASS"

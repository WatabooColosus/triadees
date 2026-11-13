from __future__ import annotations

from pathlib import Path

from triade.db import sqlite3
from triade.observability.audit_history import build_audit_history


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE hardware_senses (
                id INTEGER PRIMARY KEY, snapshot_json TEXT, recorded_at TEXT
            );
            CREATE TABLE engineering_evolution_events (
                id INTEGER PRIMARY KEY, evolution_id TEXT, event TEXT,
                decision TEXT, payload_json TEXT, created_at TEXT
            );
            CREATE TABLE evidence_remediation_audit (
                id INTEGER PRIMARY KEY, entity_type TEXT, entity_id TEXT,
                before_json TEXT, after_json TEXT, reason TEXT, created_at TEXT
            );
            CREATE TABLE neuron_certification_transitions (
                transition_id TEXT PRIMARY KEY, neuron_id INTEGER,
                from_status TEXT, to_status TEXT, reason TEXT,
                rollback_ref TEXT, created_at TEXT
            );
            INSERT INTO hardware_senses VALUES (1, '{"secret":"omitted"}', '2026-08-24T01:00:00Z');
            INSERT INTO engineering_evolution_events VALUES
                (2, 'evo-1', 'reviewed', 'hold', '{"private":true}', '2026-08-24T02:00:00Z');
            INSERT INTO evidence_remediation_audit VALUES
                (3, 'run', 'run-1', '{"before":1}', '{"after":1}', 'audit', '2026-08-24T03:00:00Z');
            INSERT INTO neuron_certification_transitions VALUES
                ('transition-1', 7, 'candidate', 'quarantined', 'failed gate',
                 'rollback:1', '2026-08-24T04:00:00Z');
            """
        )


def test_audit_history_reads_all_ledgers_without_sensitive_payloads(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "audit.db"
    _database(db_path)

    result = build_audit_history(db_path, limit=500)

    assert result["status"] == "ok"
    assert result["limit"] == 100
    assert result["counts"] == {
        "hardware_senses": 1,
        "engineering_evolution_events": 1,
        "evidence_remediation_audit": 1,
        "neuron_certification_transitions": 1,
    }
    rendered = str(result)
    assert "secret" not in rendered
    assert "private" not in rendered
    assert "before" not in rendered
    assert "after" not in rendered


def test_audit_history_does_not_create_a_missing_database(tmp_path: Path) -> None:
    db_path = tmp_path / "missing.db"

    result = build_audit_history(db_path)

    assert result["status"] == "unavailable"
    assert result["simulated"] is False
    assert not db_path.exists()

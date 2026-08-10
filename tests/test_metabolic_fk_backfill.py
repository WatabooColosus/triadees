from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.backfill_metabolic_fk_parents import apply, inspect, rollback


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "triade.db"
    with sqlite3.connect(db) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys=OFF;
            CREATE TABLE metabolic_cycle (
                cycle_id INTEGER PRIMARY KEY, started_at TEXT NOT NULL,
                finished_at TEXT, status TEXT NOT NULL, mode TEXT NOT NULL,
                error TEXT, summary_json TEXT DEFAULT '{}');
            CREATE TABLE metabolic_needs (
                need_id TEXT PRIMARY KEY, cycle_id INTEGER NOT NULL, kind TEXT NOT NULL,
                priority INTEGER NOT NULL, evidence_json TEXT NOT NULL,
                estimated_cost_json TEXT NOT NULL, risk TEXT NOT NULL,
                status TEXT NOT NULL, authorization_policy TEXT NOT NULL,
                success_condition TEXT, expires_at TEXT, created_at TEXT NOT NULL,
                started_at TEXT, finished_at TEXT, result_json TEXT,
                FOREIGN KEY(cycle_id) REFERENCES metabolic_cycle(cycle_id));
            CREATE TABLE metabolic_receipts (
                receipt_id TEXT PRIMARY KEY, cycle_id INTEGER NOT NULL,
                need_id TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL,
                started_at TEXT NOT NULL, finished_at TEXT,
                FOREIGN KEY(cycle_id) REFERENCES metabolic_cycle(cycle_id),
                FOREIGN KEY(need_id) REFERENCES metabolic_needs(need_id));
            INSERT INTO metabolic_receipts VALUES
                ('r1',7,'budget_check-abcdef123456','evaluate','skipped',
                 '2026-01-01T00:00:00+00:00','2026-01-01T00:00:01+00:00'),
                ('r2',-1,'health_check-abcdef654321','authorize','denied',
                 '2026-01-01T00:01:00+00:00','2026-01-01T00:01:01+00:00');
            INSERT INTO metabolic_cycle VALUES
                (7,'2026-01-01T00:00:00+00:00',NULL,'completed','full',NULL,'{}');
            """
        )
    return db


def test_backfill_es_reversible_y_no_borra_recibos(tmp_path: Path) -> None:
    db = _db(tmp_path)
    before = inspect(db)
    assert before["violations"]["total"] == 3
    assert before["missing_need_parents"] == 2
    assert before["cycle_ids"] == [-1]

    applied = apply(db, tmp_path / "manifests")
    assert applied["after"]["total"] == 0
    manifest = Path(applied["manifest"])
    assert manifest.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(db) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM metabolic_receipts").fetchone()[0]
            == 2
        )

    reverted = rollback(db, manifest)
    assert reverted["after"]["total"] == before["violations"]["total"]
    with sqlite3.connect(db) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM metabolic_receipts").fetchone()[0]
            == 2
        )


def test_apply_es_idempotente(tmp_path: Path) -> None:
    db = _db(tmp_path)
    apply(db, tmp_path / "manifests")

    second = apply(db, tmp_path / "manifests")

    assert second["inserted_need_ids"] == []
    assert second["inserted_cycle_ids"] == []
    assert second["after"]["total"] == 0

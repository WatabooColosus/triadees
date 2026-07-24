"""Tests para el Event Engine de TriadeOS."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from triade.os.contracts import EventRule
from triade.os.event_engine import EventEngine, BUILTIN_RULES


SCHEMA_SQL = Path(__file__).resolve().parents[1] / "triade" / "memory" / "schemas.sql"
MIGRATION_003 = Path(__file__).resolve().parents[1] / "triade" / "memory" / "migrations" / "003_living_workers.sql"
MIGRATION_005 = Path(__file__).resolve().parents[1] / "triade" / "memory" / "migrations" / "005_triade_os.sql"


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test_triade.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if SCHEMA_SQL.exists():
        conn.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    if MIGRATION_003.exists():
        conn.executescript(MIGRATION_003.read_text(encoding="utf-8"))
    if MIGRATION_005.exists():
        conn.executescript(MIGRATION_005.read_text(encoding="utf-8"))
    conn.close()
    return db_path


@pytest.fixture()
def engine(db: Path) -> EventEngine:
    return EventEngine(db_path=db)


def _insert_event(conn: sqlite3.Connection, event_type: str, severity: str = "ok", message: str = "") -> int:
    cursor = conn.execute(
        """INSERT INTO worker_events (event_type, status, message, created_at)
        VALUES (?, ?, ?, datetime('now'))""",
        (event_type, severity, message),
    )
    return int(cursor.lastrowid)


class TestBuiltinRules:
    def test_builtin_rules_exist(self) -> None:
        assert len(BUILTIN_RULES) >= 5

    def test_builtin_rules_have_required_fields(self) -> None:
        for rule in BUILTIN_RULES:
            assert rule.event_type_pattern
            assert rule.action
            assert rule.priority > 0


class TestEventRuleRegistration:
    def test_register_custom_rule(self, engine: EventEngine) -> None:
        initial_count = len(engine.get_rules())
        engine.register_rule(EventRule(
            event_type_pattern=r"^custom_event$",
            action="custom_action",
            priority=10,
        ))
        assert len(engine.get_rules()) == initial_count + 1

    def test_clear_custom_rules(self, engine: EventEngine) -> None:
        engine.register_rule(EventRule(event_type_pattern=r"^test$", action="test"))
        engine.clear_custom_rules()
        assert len(engine.get_rules()) == len(BUILTIN_RULES)


class TestEventEngineScan:
    def test_scan_empty_events(self, engine: EventEngine) -> None:
        tasks = engine.scan()
        assert tasks == []

    def test_scan_creates_task_for_matching_event(self, engine: EventEngine, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        _insert_event(conn, "error_recorded", severity="warning", message="test error")
        conn.close()

        tasks = engine.scan()
        assert len(tasks) >= 1
        assert tasks[0]["task_type"] == "neuron_candidate_formation"

    def test_scan_does_not_trigger_for_unmatched_event(self, engine: EventEngine, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        _insert_event(conn, "some_random_event", severity="ok", message="no match")
        conn.close()

        tasks = engine.scan()
        # Should not match any builtin rules
        matching = [t for t in tasks if t["task_type"] != "bodega_global_review"]
        assert len(matching) == 0

    def test_scan_respects_severity(self, engine: EventEngine, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        _insert_event(conn, "error_recorded", severity="info", message="low severity error")
        conn.close()

        tasks = engine.scan()
        # error_recorded rule requires severity_min="warning", info=1 < warning=2
        error_tasks = [t for t in tasks if t["task_type"] == "neuron_candidate_formation"]
        assert len(error_tasks) == 0

    def test_scan_advances_last_processed_id(self, engine: EventEngine, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        _insert_event(conn, "error_recorded", severity="warning")
        conn.close()

        engine.scan()
        last_id = engine._get_state("last_processed_event_id")
        assert last_id is not None
        assert int(last_id) > 0

    def test_scan_deduplicates_pending_tasks(self, engine: EventEngine, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        _insert_event(conn, "error_recorded", severity="warning")
        _insert_event(conn, "error_recorded", severity="warning")
        conn.close()

        engine.scan()
        # Second scan should not create duplicate tasks
        conn2 = sqlite3.connect(db)
        conn2.row_factory = sqlite3.Row
        pending = conn2.execute(
            "SELECT COUNT(*) AS c FROM worker_tasks WHERE task_type = 'neuron_candidate_formation' AND status = 'pending'"
        ).fetchone()["c"]
        conn2.close()
        # Only 1 pending task due to dedup
        assert pending <= 1


class TestEventEngineProcessSingleEvent:
    def test_process_single_event(self, engine: EventEngine, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        eid = _insert_event(conn, "learning_candidate_created", severity="ok")
        conn.close()

        tasks = engine.process_single_event(eid)
        assert len(tasks) >= 1
        assert tasks[0]["task_type"] == "pending_learning_review"

    def test_process_nonexistent_event(self, engine: EventEngine) -> None:
        tasks = engine.process_single_event(9999)
        assert tasks == []


class TestEventEngineCooldown:
    def test_cooldown_prevents_repeat(self, engine: EventEngine, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        eid = _insert_event(conn, "error_recorded", severity="warning")
        conn.close()

        # First trigger
        engine.process_single_event(eid)
        # Set cooldown
        from triade.core.contracts import utc_now
        engine._set_state("cooldown:neuron_candidate_formation:error_recorded", utc_now())

        # Second trigger should be blocked by cooldown
        tasks = engine.process_single_event(eid)
        error_tasks = [t for t in tasks if t["task_type"] == "neuron_candidate_formation"]
        assert len(error_tasks) == 0


class TestEventEngineDoctor:
    def test_doctor(self, engine: EventEngine) -> None:
        report = engine.doctor()
        assert report["status"] == "ok"
        assert report["rules_count"] >= len(BUILTIN_RULES)
        assert report["last_processed_event_id"] == 0
        assert "builtin_rules" in report


class TestMatchingLogic:
    def test_matches_regex_pattern(self) -> None:
        assert EventEngine._matches_rule("error_recorded", "warning", BUILTIN_RULES[0])
        assert EventEngine._matches_rule("error_foo_bar", "warning", BUILTIN_RULES[0])
        assert not EventEngine._matches_rule("info_event", "warning", BUILTIN_RULES[0])

    def test_severity_comparison(self) -> None:
        assert EventEngine._matches_rule("error", "critical", BUILTIN_RULES[0])
        assert EventEngine._matches_rule("error", "error", BUILTIN_RULES[0])
        assert EventEngine._matches_rule("error", "warning", BUILTIN_RULES[0])
        assert not EventEngine._matches_rule("error", "ok", BUILTIN_RULES[0])
        assert not EventEngine._matches_rule("error", "info", BUILTIN_RULES[0])

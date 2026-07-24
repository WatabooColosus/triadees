"""Tests para el Neuron Scheduler de TriadeOS."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.os.neuron_scheduler import NeuronScheduler


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


def _insert_neuron(conn: sqlite3.Connection, name: str, status: str = "experimental", domain: str = "test") -> int:
    cursor = conn.execute(
        """INSERT INTO neurons (name, mission, domain, status, rules, triggers,
        inputs_allowed, outputs_allowed, forbidden_actions, success_metrics,
        evidence_required, activation_policy, contract_json, created_at)
        VALUES (?, ?, ?, ?, '[]', '[]', '[]', '[]', '[]', '[]', '[]', '{}', '{}', datetime('now'))""",
        (name, f"Mision de {name}", domain, status),
    )
    conn.commit()
    return int(cursor.lastrowid)


def _insert_activity(conn: sqlite3.Connection, neuron_id: int, activation_type: str = "scheduled") -> None:
    conn.execute(
        """INSERT INTO neuron_activity (neuron_id, activation_type, created_at)
        VALUES (?, ?, datetime('now'))""",
        (neuron_id, activation_type),
    )
    conn.commit()


def _insert_work_cycle(conn: sqlite3.Connection, neuron_id: int, status: str = "completed") -> None:
    conn.execute(
        """INSERT INTO neuron_work_cycles (mission_id, neuron_id, status)
        VALUES (?, ?, ?)""",
        (1, neuron_id, status),
    )
    conn.commit()


@pytest.fixture()
def scheduler(db: Path) -> NeuronScheduler:
    return NeuronScheduler(db_path=db)


class TestComputePriorities:
    def test_empty_neurons(self, scheduler: NeuronScheduler) -> None:
        priorities = scheduler.compute_priorities()
        assert priorities == []

    def test_returns_experimental_neurons(self, scheduler: NeuronScheduler, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        _insert_neuron(conn, "TestNeuron", status="experimental")
        conn.close()

        priorities = scheduler.compute_priorities()
        assert len(priorities) == 1
        assert priorities[0].neuron_name == "TestNeuron"

    def test_returns_multiple_statuses(self, scheduler: NeuronScheduler, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        _insert_neuron(conn, "N1", status="experimental")
        _insert_neuron(conn, "N2", status="active_assistant")
        _insert_neuron(conn, "N3", status="trusted_worker")
        _insert_neuron(conn, "N4", status="stable")
        _insert_neuron(conn, "N5", status="candidate")
        conn.close()

        priorities = scheduler.compute_priorities()
        names = {p.neuron_name for p in priorities}
        assert "N1" in names
        assert "N2" in names
        assert "N3" in names
        assert "N4" in names
        assert "N5" not in names  # candidate not included

    def test_sorted_by_priority(self, scheduler: NeuronScheduler, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        _insert_neuron(conn, "OldNeuron", status="experimental")
        _insert_neuron(conn, "NewNeuron", status="experimental")
        _insert_activity(conn, 1)  # old neuron has activity
        conn.close()

        priorities = scheduler.compute_priorities()
        if len(priorities) >= 2:
            assert priorities[0].priority_score >= priorities[1].priority_score

    def test_evidence_gap_computed(self, scheduler: NeuronScheduler, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        _insert_neuron(conn, "NoEvidence", status="experimental")
        conn.close()

        priorities = scheduler.compute_priorities()
        assert len(priorities) == 1
        assert priorities[0].evidence_gap > 0.0

    def test_staleness_computed(self, scheduler: NeuronScheduler, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        _insert_neuron(conn, "StaleNeuron", status="experimental")
        conn.close()

        priorities = scheduler.compute_priorities()
        assert len(priorities) == 1
        assert priorities[0].staleness == 1.0  # No activity = max staleness

    def test_priority_range(self, scheduler: NeuronScheduler, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        _insert_neuron(conn, "TestRange", status="experimental")
        conn.close()

        priorities = scheduler.compute_priorities()
        assert len(priorities) == 1
        assert 0.0 <= priorities[0].priority_score <= 1.0


class TestScheduleWakeups:
    def test_schedule_creates_tasks(self, scheduler: NeuronScheduler, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        _insert_neuron(conn, "WakeMe", status="experimental")
        conn.close()

        scheduled = scheduler.schedule_wakeups(max_wakeups=3)
        assert len(scheduled) == 1
        assert scheduled[0]["neuron_name"] == "WakeMe"
        assert "task_id" in scheduled[0]

    def test_schedule_respects_max_wakeups(self, scheduler: NeuronScheduler, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        for i in range(10):
            _insert_neuron(conn, f"N{i}", status="experimental")
        conn.close()

        scheduled = scheduler.schedule_wakeups(max_wakeups=3)
        assert len(scheduled) <= 3

    def test_schedule_skips_low_reputation(self, scheduler: NeuronScheduler, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        nid = _insert_neuron(conn, "LowRep", status="experimental")
        # Insert many failed work cycles to drive reputation below 0.2
        for _ in range(20):
            _insert_work_cycle(conn, nid, status="failed")
        conn.close()

        scheduled = scheduler.schedule_wakeups(max_wakeups=5)
        names = [s["neuron_name"] for s in scheduled]
        assert "LowRep" not in names

    def test_schedule_logs_priority(self, scheduler: NeuronScheduler, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        _insert_neuron(conn, "Logged", status="experimental")
        conn.close()

        scheduler.schedule_wakeups(max_wakeups=1)
        conn2 = sqlite3.connect(db)
        conn2.row_factory = sqlite3.Row
        logs = conn2.execute("SELECT COUNT(*) AS c FROM neuron_priority_log").fetchone()["c"]
        conn2.close()
        assert logs >= 1


class TestRecordActivation:
    def test_record_activation(self, scheduler: NeuronScheduler, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        nid = _insert_neuron(conn, "ActNeuron", status="experimental")
        conn.close()

        scheduler.record_activation(nid, duration_ms=1500, success=True)
        conn2 = sqlite3.connect(db)
        conn2.row_factory = sqlite3.Row
        count = conn2.execute(
            "SELECT COUNT(*) AS c FROM neuron_activity WHERE neuron_id = ?", (nid,)
        ).fetchone()["c"]
        conn2.close()
        assert count == 1

    def test_record_failed_activation(self, scheduler: NeuronScheduler, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        nid = _insert_neuron(conn, "FailNeuron", status="experimental")
        conn.close()

        scheduler.record_activation(nid, duration_ms=500, success=False)
        conn2 = sqlite3.connect(db)
        conn2.row_factory = sqlite3.Row
        row = conn2.execute(
            "SELECT activation_type FROM neuron_activity WHERE neuron_id = ?", (nid,)
        ).fetchone()
        conn2.close()
        assert row["activation_type"] == "failed_scheduled"


class TestDoctor:
    def test_doctor_empty(self, scheduler: NeuronScheduler) -> None:
        report = scheduler.doctor()
        assert report["status"] == "ok"
        assert report["total_active_neurons"] == 0
        assert report["priorities_computed"] == 0

    def test_doctor_with_neurons(self, scheduler: NeuronScheduler, db: Path) -> None:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        _insert_neuron(conn, "D1", status="experimental")
        _insert_neuron(conn, "D2", status="stable")
        conn.close()

        report = scheduler.doctor()
        assert report["status"] == "ok"
        assert report["total_active_neurons"] == 2
        assert report["priorities_computed"] == 2
        assert len(report["top_priorities"]) == 2

"""Repeated educational abstentions do not invent new evidence receipts."""

from __future__ import annotations

import json
import sqlite3

from triade.neurons.education_resolver import NeuronEducationResolver


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE neuron_education_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, neuron_id INTEGER, "
        "event_type TEXT, payload_json TEXT, created_at TEXT)"
    )
    return conn


def _payload(n=0):
    return {
        "baseline": None,
        "post": None,
        "applied_runs": n,
        "reason": f"{n} measured run(s), minimum 5",
        "rollback_ref": "attempted-version",
        "rolled_back": False,
    }


def test_repeated_insufficient_education_does_not_add_receipts():
    conn = _conn()
    try:
        resolver = NeuronEducationResolver(":memory:")
        resolver._record_event(
            conn, "lesson-1", 13, "education_insufficient_evidence", _payload()
        )
        resolver._record_event(
            conn, "lesson-1", 13, "education_insufficient_evidence", _payload()
        )
        rows = conn.execute(
            "SELECT payload_json FROM neuron_education_events"
        ).fetchall()
        assert len(rows) == 1
        assert json.loads(rows[0][0])["applied_runs"] == 0
    finally:
        conn.close()


def test_new_measured_runs_must_add_new_receipt():
    conn = _conn()
    try:
        resolver = NeuronEducationResolver(":memory:")
        resolver._record_event(
            conn, "lesson-1", 13, "education_insufficient_evidence", _payload()
        )
        resolver._record_event(
            conn, "lesson-1", 13, "education_insufficient_evidence", _payload(1)
        )
        resolver._record_event(
            conn, "lesson-1", 13, "education_insufficient_evidence", _payload(1)
        )
        rows = conn.execute(
            "SELECT payload_json FROM neuron_education_events"
        ).fetchall()
        assert [json.loads(x[0])["applied_runs"] for x in rows] == [0, 1]
    finally:
        conn.close()


def test_distinct_sessions_and_verified_decisions_are_never_deduplicated():
    conn = _conn()
    try:
        resolver = NeuronEducationResolver(":memory:")
        resolver._record_event(
            conn, "lesson-1", 13, "education_insufficient_evidence", _payload()
        )
        resolver._record_event(
            conn, "lesson-2", 13, "education_insufficient_evidence", _payload()
        )
        resolver._record_event(conn, "lesson-1", 13, "education_improved", _payload(5))
        resolver._record_event(conn, "lesson-1", 13, "education_improved", _payload(5))
        assert (
            conn.execute("SELECT COUNT(*) FROM neuron_education_events").fetchone()[0]
            == 4
        )
    finally:
        conn.close()


def test_corrupt_old_receipt_does_not_silence_new_evidence():
    conn = _conn()
    try:
        resolver = NeuronEducationResolver(":memory:")
        conn.execute(
            "INSERT INTO neuron_education_events "
            "(session_id,neuron_id,event_type,payload_json,created_at) "
            "VALUES(?,?,?,?,?)",
            ("lesson-1", 13, "education_insufficient_evidence", "{broken", "test"),
        )
        resolver._record_event(
            conn, "lesson-1", 13, "education_insufficient_evidence", _payload()
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM neuron_education_events").fetchone()[0]
            == 2
        )
    finally:
        conn.close()

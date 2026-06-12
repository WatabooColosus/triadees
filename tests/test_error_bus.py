"""Tests de observabilidad interna."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.core.error_bus import query_internal_errors, record_internal_error


def make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
    return db_path


def test_record_internal_error_is_queryable(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)

    try:
        raise RuntimeError("controlled failure")
    except RuntimeError as exc:
        event_id = record_internal_error(
            "tests.controlled",
            exc,
            run_id="run-observability-test",
            payload={"module": "tests", "function": "test_record_internal_error_is_queryable", "operation": "controlled_raise"},
            db_path=db_path,
        )

    assert event_id is not None
    errors = query_internal_errors(scope="tests.controlled", db_path=db_path)
    assert len(errors) == 1
    assert errors[0]["run_ref"] == "run-observability-test"
    assert errors[0]["payload"]["context"]["operation"] == "controlled_raise"

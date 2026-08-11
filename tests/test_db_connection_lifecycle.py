from __future__ import annotations

import concurrent.futures
import re
from pathlib import Path

import pytest

from triade.db import sqlite3


def test_productive_code_uses_canonical_sqlite_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    bypasses: list[str] = []
    direct_import = re.compile(r"^import sqlite3(?:\s+as\s+\w+)?$", re.MULTILINE)
    for source_root in (root / "triade", root / "apps"):
        for source in source_root.rglob("*.py"):
            if source == root / "triade/db/sqlite3.py":
                continue
            if direct_import.search(source.read_text(encoding="utf-8")):
                bypasses.append(str(source.relative_to(root)))
    assert bypasses == []


def test_context_commits_and_closes(tmp_path: Path) -> None:
    database = tmp_path / "commit.db"
    before = sqlite3.connection_metrics()

    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE events (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO events VALUES (1)")

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")

    with sqlite3.connect(database) as reader:
        assert reader.execute("SELECT value FROM events").fetchone()[0] == 1

    after = sqlite3.connection_metrics()
    assert after["open_connections"] == before["open_connections"]
    assert after["opened_total"] - before["opened_total"] == 2
    assert after["closed_total"] - before["closed_total"] == 2


def test_context_rolls_back_and_closes(tmp_path: Path) -> None:
    database = tmp_path / "rollback.db"
    with sqlite3.connect(database) as setup:
        setup.execute("CREATE TABLE events (value INTEGER NOT NULL)")

    with (
        pytest.raises(RuntimeError, match="abort"),
        sqlite3.connect(database) as connection,
    ):
        connection.execute("INSERT INTO events VALUES (1)")
        raise RuntimeError("abort")

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")
    with sqlite3.connect(database) as reader:
        assert reader.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_concurrent_wal_connections_return_to_baseline(tmp_path: Path) -> None:
    database = tmp_path / "concurrent.db"
    with sqlite3.connect(database) as setup:
        setup.execute("PRAGMA journal_mode=WAL")
        setup.execute("CREATE TABLE events (worker INTEGER NOT NULL)")

    before = sqlite3.connection_metrics()["open_connections"]

    def write(worker: int) -> None:
        with sqlite3.connect(database, timeout=10) as connection:
            connection.execute("PRAGMA busy_timeout=10000")
            connection.execute("INSERT INTO events VALUES (?)", (worker,))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write, range(50)))

    assert sqlite3.connection_metrics()["open_connections"] == before
    with sqlite3.connect(database) as reader:
        assert reader.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 50


def test_resource_metrics_report_live_descriptors(tmp_path: Path) -> None:
    database = tmp_path / "resources.db"
    before = sqlite3.resource_metrics(database)
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        during = sqlite3.resource_metrics(database)
        assert during["open_connections"] == before["open_connections"] + 1
        assert during["db_file_descriptors"] >= 1
        assert during["process_file_descriptors"] >= during["db_file_descriptors"]
        assert during["rss_mb"] > 0
    finally:
        connection.close()
    assert (
        sqlite3.resource_metrics(database)["open_connections"]
        == before["open_connections"]
    )

"""Regresión del respaldo SQLite WAL y de la continuidad de Tríade en Colab."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.triade_colab_continuity_guard import (
    _image_from_live_sqlite,
    safe_snapshot,
)


class FakeCoordinator:
    def __init__(self, root: Path) -> None:
        self.DRIVE = root / "Drive"
        self.DRIVE.mkdir()
        self.STORE = self.DRIVE / "continuidad_runtime" / "v1"
        self.STORE.mkdir(parents=True)
        self.INDEX = self.STORE / "active.json"
        self.DB = root / "triade.db"
        self.engine = SimpleNamespace(
            STATE=root / "state", repo_status=lambda: "test-sha"
        )
        self.engine.STATE.mkdir()
        self.SUMMARY = (
            "neurons",
            "autonomous_tasks",
            "neuron_education_sessions",
            "neuron_education_applications",
            "metabolic_cycle",
            "auth_users",
            "auth_email_identities",
            "worker_runs",
            "governed_research_runs",
        )
        with sqlite3.connect(self.DB) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """CREATE TABLE neurons(id INTEGER PRIMARY KEY);
                CREATE TABLE autonomous_tasks(id INTEGER PRIMARY KEY);
                CREATE TABLE neuron_education_sessions(id INTEGER PRIMARY KEY);
                CREATE TABLE neuron_education_applications(id INTEGER PRIMARY KEY);
                CREATE TABLE metabolic_cycle(id INTEGER PRIMARY KEY);
                CREATE TABLE auth_users(user_id TEXT PRIMARY KEY);
                CREATE TABLE auth_email_identities(id INTEGER PRIMARY KEY);
                CREATE TABLE worker_runs(id INTEGER PRIMARY KEY);
                CREATE TABLE governed_research_runs(id INTEGER PRIMARY KEY);"""
            )
            conn.execute("INSERT INTO auth_users VALUES('ownerA')")
            conn.execute("INSERT INTO neurons VALUES(1)")
            conn.executemany(
                "INSERT INTO autonomous_tasks VALUES(?)",
                [(i,) for i in range(1, 13)],
            )
            conn.executemany(
                "INSERT INTO metabolic_cycle VALUES(?)",
                [(i,) for i in range(1, 8)],
            )
        self.held_wal = sqlite3.connect(self.DB)
        self.held_wal.execute("PRAGMA journal_mode=WAL")
        self.held_wal.execute("INSERT INTO autonomous_tasks VALUES(13)")
        self.held_wal.commit()

    def inspect_db(self, path: Path) -> dict:
        uri = "file:" + str(Path(path).resolve()) + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            counts = {
                name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                for name in self.SUMMARY
            }
            owners = [row[0] for row in conn.execute("SELECT user_id FROM auth_users")]
        lineage = hashlib.sha256("\n".join(sorted(owners)).encode()).hexdigest()[:16]
        return {"lineage": lineage, "counts": counts, "integrity": "ok"}

    def digest(self, path: Path) -> str:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def atomic_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    def validated_snapshot(self, path: Path) -> dict | None:
        meta = json.loads(path.with_suffix(".json").read_text())
        if meta["size"] != path.stat().st_size or meta["sha256"] != self.digest(path):
            return None
        return {"info": self.inspect_db(path)}


def test_wal_image_consolidated_in_single_sqlite_file(tmp_path: Path) -> None:
    manager = FakeCoordinator(tmp_path)
    image = tmp_path / "private.db"
    _image_from_live_sqlite(manager.DB, image)
    assert manager.inspect_db(image)["counts"]["autonomous_tasks"] == 13
    assert not image.with_name(image.name + "-wal").exists()
    with sqlite3.connect(image) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    manager.held_wal.close()


def test_pointer_published_only_for_verified_image(tmp_path: Path) -> None:
    manager = FakeCoordinator(tmp_path)
    live = manager.inspect_db(manager.DB)
    older = manager.STORE / "memoria-antigua.sqlite3"
    _image_from_live_sqlite(manager.DB, older)
    with sqlite3.connect(older) as conn:
        conn.execute("DELETE FROM autonomous_tasks WHERE id > 5")
    old_meta = {"sha256": manager.digest(older), "size": older.stat().st_size}
    manager.atomic_json(older.with_suffix(".json"), old_meta)
    manager.atomic_json(
        manager.INDEX,
        {
            "file": older.name,
            "lineage": live["lineage"],
            "sha256": old_meta["sha256"],
            "counts": live["counts"],
        },
    )
    previous = manager.INDEX.read_text()

    result = safe_snapshot(manager, force=True)
    assert result["status"] == "saved"
    index = json.loads(manager.INDEX.read_text())
    image = manager.STORE / index["file"]
    assert manager.inspect_db(image)["counts"] == index["counts"]
    assert index["counts"]["autonomous_tasks"] == 13
    assert older.exists() and manager.INDEX.read_text() != previous
    history_dir = manager.STORE / "index_history_guarded"
    history = next(history_dir.glob("active-before-*.json"))
    assert json.loads(history.read_text())["file"] == older.name
    manager.held_wal.close()


def test_regression_blocks_pointer_update(tmp_path: Path) -> None:
    manager = FakeCoordinator(tmp_path)
    live = manager.inspect_db(manager.DB)
    impossible = {**live["counts"], "autonomous_tasks": 100000}
    manager.atomic_json(
        manager.INDEX,
        {
            "lineage": live["lineage"],
            "file": "existing.sqlite3",
            "counts": impossible,
            "sha256": "previous",
        },
    )
    previous = manager.INDEX.read_text()
    with pytest.raises(RuntimeError, match="CONTINUIDAD_PROTEGIDA"):
        safe_snapshot(manager, force=True)
    assert manager.INDEX.read_text() == previous
    manager.held_wal.close()

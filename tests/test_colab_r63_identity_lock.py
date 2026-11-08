"""Regression: pinned Colab R6.3 preflight must not write live SQLite."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from tools import triade_colab_continuity_r631 as continuity
from triade.core.identity_continuity import IdentityContinuity


def _anchored_db(tmp_path):
    db = tmp_path / "triade.db"
    status = IdentityContinuity(db).verify(run_id="initial")
    assert status["integrity"] == "verified"
    return db


def test_r63_identity_verification_is_read_only_during_wal_writer(tmp_path):
    db = _anchored_db(tmp_path)
    with sqlite3.connect(db) as conn:
        initial_logs = conn.execute(
            "SELECT COUNT(*) FROM identity_continuity_log"
        ).fetchone()[0]
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("BEGIN IMMEDIATE")
        # An active writer prevents schema DDL but must not prevent
        # observation of a committed identity through the WAL snapshot.
        status = continuity._verify_existing_identity_read_only(db)
        assert status["integrity"] == "verified"
        assert conn.in_transaction
        conn.rollback()
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM identity_continuity_log").fetchone()[0]
            == initial_logs
        )


def test_r63_read_only_preflight_fails_when_anchor_missing(tmp_path):
    db = _anchored_db(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM identity_manifest_anchor WHERE singleton=1")
    with pytest.raises(RuntimeError, match="Ancla de identidad ausente"):
        continuity._verify_existing_identity_read_only(db)
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM identity_manifest_anchor").fetchone()[0]
            == 0
        )


def test_r63_read_only_preflight_fails_on_identity_tampering(tmp_path):
    db = _anchored_db(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE identity_core SET value='altered' WHERE key='entity_name'")
    with pytest.raises(RuntimeError, match="identidad divergente"):
        continuity._verify_existing_identity_read_only(db)


def test_r63_identity_hook_is_restored_after_success_and_error(tmp_path):
    db = _anchored_db(tmp_path)

    def original():
        raise AssertionError("schema-changing legacy checker must not run")

    r5 = SimpleNamespace(check_working_identity=original)

    class FakeR63:
        def prepare(self, runtime):
            assert runtime.check_working_identity()["integrity"] == "verified"
            return {"tests": "pass"}

        def apply_and_restart(self, runtime, approval):
            assert approval == "ACTUALIZAR R6.3"
            assert runtime.check_working_identity()["integrity"] == "verified"
            return {"status": "active_candidate"}

    assert (
        continuity._install_r63_with_read_only_identity(r5, FakeR63(), db)["status"]
        == "active_candidate"
    )
    assert r5.check_working_identity is original

    class FailingR63(FakeR63):
        def prepare(self, runtime):
            assert runtime.check_working_identity()["integrity"] == "verified"
            raise RuntimeError("staging failed")

    with pytest.raises(RuntimeError, match="staging failed"):
        continuity._install_r63_with_read_only_identity(r5, FailingR63(), db)
    assert r5.check_working_identity is original

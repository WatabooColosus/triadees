from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.core.identity_continuity import IdentityContinuity
from triade.core.safe_file_ops import safe_patch_file
from triade.federation.federation import Federation


def _identity_rows(db_path: Path) -> list[tuple[object, ...]]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT key, value, category, confidence FROM identity_core ORDER BY key"
        ).fetchall()


def test_restart_preserves_identity_and_records_continuity(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    first = IdentityContinuity(db_path).verify(run_id="run-one")
    second = IdentityContinuity(db_path).verify(run_id="run-two")

    assert first["integrity"] == "verified"
    assert first["continuity_from_previous_run"] is False
    assert second["integrity"] == "verified"
    assert second["continuity_from_previous_run"] is True
    assert second["manifest_hash"] == first["manifest_hash"]


def test_identity_core_tamper_enters_degraded_safe_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    continuity = IdentityContinuity(db_path)
    continuity.verify(run_id="before-tamper")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE identity_core SET value = 'tampered' WHERE key = 'entity_name'"
        )

    result = continuity.verify(run_id="after-tamper")

    assert result["integrity"] == "degraded_safe"
    assert result["tamper_detected"] is True
    assert result["degraded_mode"] is True
    assert "identity_core_hash" in result["mismatches"]


def test_safe_file_ops_cannot_modify_identity_core_path(tmp_path: Path) -> None:
    target = tmp_path / "identity_core.json"
    target.write_text("original", encoding="utf-8")

    result = safe_patch_file(str(target), "modified", "full", dry_run=False)

    assert result["status"] == "blocked_forbidden_zone"
    assert target.read_text(encoding="utf-8") == "original"


def test_migration_and_federation_do_not_modify_identity_core(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    continuity = IdentityContinuity(db_path)
    before = _identity_rows(db_path)

    Federation(db_path=db_path).register_node(
        node_id="identity-safe-node",
        name="Identity safe node",
        endpoint="http://127.0.0.1:9999",
        capabilities={"observer": True},
    )
    continuity.verify(run_id="after-federation")

    assert _identity_rows(db_path) == before


def test_explicit_migration_backup_restores_expected_hash(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    continuity = IdentityContinuity(db_path)
    original = continuity.verify(run_id="original")
    migrated = continuity.migrate_anchor(
        approved_by="human:test-owner",
        reason="exercise explicit migration and recovery",
        backup_dir=tmp_path / "backups",
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE identity_core SET value = 'tampered' WHERE key = 'entity_name'"
        )
    assert continuity.verify(run_id="tampered")["integrity"] == "degraded_safe"

    restored = continuity.restore_to_sandbox(
        migrated["backup_ref"], tmp_path / "restore" / "triade.db"
    )

    assert restored["status"] == "verified"
    assert restored["production_overwritten"] is False
    assert restored["identity"]["manifest_hash"] == original["manifest_hash"]

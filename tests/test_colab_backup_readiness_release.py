"""R5 compatibility: new Colab package overlays never write production memory."""

from __future__ import annotations

import ast
import inspect
import os
import time
from pathlib import Path

from cryptography.fernet import Fernet
from file_permission_helpers import set_file_mode

from tools import triade_colab_release as installer
from tools.colab_patch_sources import (
    backup_key_resolution,
    mission_planner_backup_readiness,
)
from triade.db import sqlite3


def _fixture_database(tmp_path):
    path = tmp_path / "triade.db"
    schema = Path(__file__).resolve().parents[1] / "triade/memory/schemas.sql"
    with sqlite3.connect(path) as conn:
        conn.executescript(schema.read_text(encoding="utf-8"))
    return path


def test_colab_staged_sources_are_parseable_and_installed_with_verification():
    root = Path(__file__).resolve().parents[1]
    for path in (
        "tools/colab_patch_sources/backup_key_resolution.py",
        "tools/colab_patch_sources/mission_planner_backup_readiness.py",
    ):
        ast.parse((root / path).read_text(encoding="utf-8"), filename=path)
    for function in (
        installer._apply_runtime_path_patches,
        installer._runtime_patches_match,
    ):
        source = inspect.getsource(function)
        assert (
            '"mission_planner_backup_readiness": "triade/workers/mission_planner.py"'
            in source
        )


def test_colab_r5_planner_protects_key_without_rotating_or_chmodding(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        mission_planner_backup_readiness,
        "EncryptedBackup",
        backup_key_resolution.EncryptedBackup,
    )
    monkeypatch.delenv("TRIADE_BACKUP_KEY", raising=False)
    key_file = tmp_path / "key"
    key_file.write_bytes(Fernet.generate_key())
    set_file_mode(key_file, 0o600)
    monkeypatch.setenv("TRIADE_BACKUP_KEY_FILE", str(key_file))
    db = _fixture_database(tmp_path)
    original = key_file.read_bytes()

    plan = mission_planner_backup_readiness.MissionPlanner(db).plan_cycle()
    assert any(task.task_type == "encrypted_backup" for task in plan)

    set_file_mode(key_file, 0o644)
    assert backup_key_resolution.EncryptedBackup.key_status()["usable"] is False
    plan = mission_planner_backup_readiness.MissionPlanner(db).plan_cycle()
    assert all(task.task_type != "encrypted_backup" for task in plan)
    assert key_file.read_bytes() == original

    # Now the key is private again, but the most recent backup remains inside
    # the writer's cooldown. Neither path may fabricate a new backup task.
    set_file_mode(key_file, 0o600)
    folder = tmp_path / "artifacts" / "backups"
    folder.mkdir(parents=True)
    recent = folder / "triade-test.db.gz.fernet"
    recent.write_bytes(b"cooldown fixture")
    from triade.core.error_bus import query_internal_errors

    before = query_internal_errors(db_path=db, limit=40) or []
    before_count = sum("backup_key_" in str(x.get("task_type", "")) for x in before)
    plan = mission_planner_backup_readiness.MissionPlanner(db).plan_cycle()
    assert all(task.task_type != "encrypted_backup" for task in plan)
    after = query_internal_errors(db_path=db, limit=40) or []
    after_count = sum("backup_key_" in str(x.get("task_type", "")) for x in after)
    assert after_count == before_count
    older = time.time() - 301
    os.utime(recent, (older, older))
    plan = mission_planner_backup_readiness.MissionPlanner(db).plan_cycle()
    assert any(task.task_type == "encrypted_backup" for task in plan)

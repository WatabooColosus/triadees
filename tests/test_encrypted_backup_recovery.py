import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet, InvalidToken

from triade.memory.encrypted_backup import EncryptedBackup
from triade.workers.worker_loop import WorkerLoop


def source(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE semantic_memory(id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO semantic_memory(value) VALUES ('remember me')")
        conn.execute(
            "CREATE TABLE autonomous_tasks(id TEXT,status TEXT,result_ref TEXT)"
        )
        conn.execute("INSERT INTO autonomous_tasks VALUES ('t','blocked',NULL)")


def test_valid_backup_restores_sandbox_and_not_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIADE_BACKUP_KEY", Fernet.generate_key().decode())
    db = tmp_path / "production.db"
    source(db)
    backup = EncryptedBackup(db, tmp_path / "backups", minimum_interval_seconds=0)
    created = backup.create()
    restored = backup.restore_to_sandbox(
        tmp_path / "backups" / created["file"], tmp_path / "sandbox.db"
    )
    assert restored["status"] == "restored_sandbox"
    assert restored["production_overwritten"] is False
    assert restored["restored"]["semantic_memory_count"] == 1
    assert restored["restored"]["task_states"] == {"blocked": 1}


def test_backup_and_manifest_are_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIADE_BACKUP_KEY", Fernet.generate_key().decode())
    db = tmp_path / "production.db"
    source(db)
    backup = EncryptedBackup(db, tmp_path / "backups", minimum_interval_seconds=0)

    created = backup.create()
    encrypted = tmp_path / "backups" / created["file"]
    manifest = encrypted.with_suffix(encrypted.suffix + ".json")

    assert encrypted.stat().st_mode & 0o777 == 0o600
    assert manifest.stat().st_mode & 0o777 == 0o600


def test_wrong_key_and_truncated_backup_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIADE_BACKUP_KEY", Fernet.generate_key().decode())
    db = tmp_path / "db"
    source(db)
    backup = EncryptedBackup(db, tmp_path / "backups", minimum_interval_seconds=0)
    created = backup.create()
    path = tmp_path / "backups" / created["file"]
    monkeypatch.setenv("TRIADE_BACKUP_KEY", Fernet.generate_key().decode())
    with pytest.raises(InvalidToken):
        backup.verify(path)
    monkeypatch.setenv("TRIADE_BACKUP_KEY", Fernet.generate_key().decode())
    path.write_bytes(path.read_bytes()[:20])
    with pytest.raises(ValueError, match="hash_mismatch"):
        backup.verify(path)


def test_cooldown_and_production_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIADE_BACKUP_KEY", Fernet.generate_key().decode())
    db = tmp_path / "db"
    source(db)
    backup = EncryptedBackup(db, tmp_path / "backups", minimum_interval_seconds=300)
    created = backup.create()
    assert backup.create()["status"] == "blocked"
    assert (
        backup.restore(tmp_path / "backups" / created["file"], human_approved=False)[
            "status"
        ]
        == "blocked"
    )


def test_periodic_restore_drill_records_semantics_growth_and_cooldown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIADE_BACKUP_KEY", Fernet.generate_key().decode())
    db = tmp_path / "production.db"
    source(db)
    artifacts = tmp_path / "artifacts"
    backup = EncryptedBackup(db, artifacts / "backups", minimum_interval_seconds=0)
    created = backup.create()
    backup_path = artifacts / "backups" / created["file"]

    drill = backup.run_restore_drill(
        backup_path,
        sandbox_dir=artifacts / "restore-drills",
        artifacts_root=artifacts,
    )
    cooldown = backup.run_restore_drill(
        backup_path,
        sandbox_dir=artifacts / "restore-drills",
        artifacts_root=artifacts,
    )

    assert drill["status"] == "completed"
    assert drill["production_overwritten"] is False
    assert drill["semantic_verification"]["integrity_check"] == "ok"
    assert drill["semantic_verification"]["semantic_memory_count"] == 1
    assert drill["semantic_verification"]["task_states"] == {"blocked": 1}
    assert drill["storage"]["backup_bytes"] > 0
    assert drill["storage"]["artifact_bytes"] >= drill["storage"]["backup_bytes"]
    assert cooldown["status"] == "blocked"
    assert cooldown["reason"] == "restore_drill_cooldown_active"


def test_restore_drill_force_measures_growth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIADE_BACKUP_KEY", Fernet.generate_key().decode())
    db = tmp_path / "production.db"
    source(db)
    artifacts = tmp_path / "artifacts"
    backup = EncryptedBackup(db, artifacts / "backups", minimum_interval_seconds=0)
    created = backup.create()
    path = artifacts / "backups" / created["file"]
    first = backup.run_restore_drill(path, artifacts_root=artifacts, force=True)
    (artifacts / "growth.bin").write_bytes(b"x" * 4096)
    second = backup.run_restore_drill(path, artifacts_root=artifacts, force=True)
    assert first["growth_bytes"] is None
    assert second["status"] == "completed"
    assert second["growth_bytes"] >= 4096


def test_backup_key_file_requires_restricted_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_file = tmp_path / "backup.key"
    key_file.write_text(Fernet.generate_key().decode(), encoding="utf-8")
    key_file.chmod(0o644)
    monkeypatch.delenv("TRIADE_BACKUP_KEY", raising=False)
    monkeypatch.setenv("TRIADE_BACKUP_KEY_FILE", str(key_file))
    db = tmp_path / "db"
    source(db)
    backup = EncryptedBackup(db, tmp_path / "backups")
    with pytest.raises(PermissionError, match="permissions_must_be_0600"):
        backup.create()
    key_file.chmod(0o600)
    assert backup.create()["status"] == "completed"


def test_worker_backup_cooldown_is_blocked_without_false_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRIADE_BACKUP_KEY", Fernet.generate_key().decode())
    db = tmp_path / "production.db"
    source(db)
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    worker = SimpleNamespace(db_path=db)

    first = WorkerLoop._encrypted_backup(worker, None, "run", task_dir, None)
    second = WorkerLoop._encrypted_backup(worker, None, "run", task_dir, None)

    assert first["status"] == "completed"
    assert first["restore_drill"]["status"] == "completed"
    assert first["restore_drill"]["production_overwritten"] is False
    assert second["status"] == "blocked"
    assert second["reason"] == "backup_cooldown_active"

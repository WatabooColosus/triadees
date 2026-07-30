import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet, InvalidToken

from triade.memory.encrypted_backup import EncryptedBackup


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

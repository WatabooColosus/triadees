"""Only temporary SQLite/key fixtures; never user memory or real credentials."""

import hashlib
import json
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from tools import triade_colab_backup as protection
from triade.db import sqlite3


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    root, work, drive = (tmp_path / name for name in ("repo", "work", "drive"))
    for path in (root / "config", work, drive):
        path.mkdir(parents=True)
    db = root / "fixture.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE fixture_memory(value TEXT)")
        conn.execute("INSERT INTO fixture_memory VALUES ('preserved fixture')")
    (root / "config/backup_key_location.json").write_text(
        json.dumps({"key_file": r"E:\old\backup.key"})
    )
    (work / "restore_proof.json").write_text(json.dumps({"source_sha256": "a" * 64}))
    r5 = SimpleNamespace(
        ROOT=root,
        WORK=work,
        BASE=drive,
        DB=db,
        _owner_account_status=lambda path: {"fixture": True},
    )
    monkeypatch.setattr(protection, "_backend_environment", lambda r5: {})
    # repair intentionally updates the notebook environment. Register an
    # undo even when the variable did not exist before this fixture.
    monkeypatch.setenv("TRIADE_BACKUP_KEY", "")
    monkeypatch.setenv("TRIADE_BACKUP_KEY_FILE", "")
    return r5


def test_new_colab_domain_preserves_db_and_old_pointer_and_roundtrips(runtime):
    before = runtime.DB.read_bytes()
    original = (runtime.ROOT / "config/backup_key_location.json").read_bytes()
    result = protection.repair(runtime)
    assert result["status"] == "encrypted_copy_verified"
    assert result["key_resolution"] == "new_colab_domain_legacy_key_not_recovered"
    assert result["legacy_encrypted_backups_recovery"] == "not_certified"
    assert result["decryption_verified"] is True
    assert runtime.DB.read_bytes() == before
    archive = (
        runtime.WORK
        / "backup_config_history"
        / (hashlib.sha256(original).hexdigest() + ".json")
    )
    assert archive.read_bytes() == original
    active = json.loads((runtime.ROOT / "config/backup_key_location.json").read_text())
    key = protection.Path(active["key_file"])
    assert key.stat().st_mode & 0o777 == 0o600
    assert key.read_text() not in json.dumps(result)
    again = protection.repair(runtime)
    assert again["key_fingerprint"] == result["key_fingerprint"]
    assert again["file"] == result["file"]


def test_recovers_existing_drive_key_without_rotation(runtime):
    key = Fernet.generate_key()
    (runtime.BASE / "backup.key").write_bytes(key)
    result = protection.repair(runtime)
    assert result["key_resolution"] == "existing_key_recovered"
    assert result["key_fingerprint"] == protection._fingerprint(key)
    assert (protection._paths(runtime) / "backup.key").read_bytes() == key


def test_conflicting_keys_or_invalid_persistent_key_are_not_replaced(runtime):
    pointer = (runtime.ROOT / "config/backup_key_location.json").read_bytes()
    persistent = protection._paths(runtime)
    persistent.mkdir(parents=True)
    (persistent / "backup.key").write_bytes(Fernet.generate_key())
    (runtime.BASE / "backup.key").write_bytes(Fernet.generate_key())
    with pytest.raises(RuntimeError, match="multiple_backup_keys"):
        protection.repair(runtime)
    assert (runtime.ROOT / "config/backup_key_location.json").read_bytes() == pointer
    (persistent / "backup.key").write_bytes(b"invalid fixture key")
    with pytest.raises(RuntimeError, match="backup_key_invalid"):
        protection.repair(runtime)
    assert (persistent / "backup.key").read_bytes() == b"invalid fixture key"


def test_owner_failure_prevents_key_and_configuration_writes(runtime):
    def deny(path):
        raise RuntimeError("fixture owner mismatch")

    runtime._owner_account_status = deny
    with pytest.raises(RuntimeError, match="owner mismatch"):
        protection.repair(runtime)
    assert not (runtime.BASE / "operacion_colab_continua").exists()


def test_periodic_copy_only_persists_verified_matching_key_files(runtime):
    result = protection.repair(runtime)
    backup = protection._backup_instance(runtime)
    with sqlite3.connect(runtime.DB) as conn:
        conn.execute("INSERT INTO fixture_memory VALUES ('second fixture')")
    created = backup.create(force=True)
    assert created["status"] == "completed"
    replicated = protection.replicate(runtime)
    assert replicated["file"] == created["file"]
    assert replicated["file"] != result["file"]
    assert (protection._paths(runtime) / "copies" / created["file"]).is_file()
    assert protection.replicate(runtime)["file"] == created["file"]


def test_corrupt_cipher_is_not_persisted(runtime):
    protection.repair(runtime)
    backup = protection._backup_instance(runtime)
    created = backup.create(force=True)
    path = backup.backup_dir / created["file"]
    path.write_bytes(b"corrupted fixture ciphertext")
    with pytest.raises(ValueError, match="hash_mismatch"):
        protection.replicate(runtime)
    assert not (protection._paths(runtime) / "copies" / path.name).exists()


def test_persistent_symlink_is_rejected_without_writing_target(runtime, tmp_path):
    outside = tmp_path / "other-key"
    outside.write_bytes(Fernet.generate_key())
    persistent = protection._paths(runtime)
    persistent.mkdir(parents=True)
    (persistent / "backup.key").symlink_to(outside)
    before = outside.read_bytes()
    with pytest.raises(RuntimeError, match="symlink"):
        protection.repair(runtime)
    assert outside.read_bytes() == before


def test_backend_inline_key_is_reused_without_changing_original(runtime, monkeypatch):
    key = Fernet.generate_key()
    monkeypatch.setattr(
        protection,
        "_backend_environment",
        lambda r5: {"TRIADE_BACKUP_KEY": key.decode()},
    )
    result = protection.repair(runtime)
    assert result["key_fingerprint"] == protection._fingerprint(key)
    assert result["key_resolution"] == "existing_key_recovered"


def test_one_copy_watcher_is_reused_without_duplicate_threads(runtime):
    protection.start_watch(runtime)
    first = runtime._encrypted_backup_watch["thread"]
    protection.start_watch(runtime)
    try:
        assert not first.is_alive()
        assert runtime._encrypted_backup_watch["thread"].is_alive()
    finally:
        runtime._encrypted_backup_watch["stop"].set()
        runtime._encrypted_backup_watch["thread"].join(timeout=1)


def test_corrupt_source_does_not_produce_verified_backup(runtime):
    runtime.DB.write_bytes(b"not a SQLite fixture database")
    with pytest.raises((RuntimeError, sqlite3.Error)):
        protection.repair(runtime)
    assert not (runtime.WORK / "encrypted_backup_status.json").exists()


def test_missing_legacy_key_never_rekeys_existing_encrypted_corpus(runtime):
    original = (runtime.ROOT / "config/backup_key_location.json").read_bytes()
    legacy = runtime.ROOT / "artifacts/backups/triade-legacy.db.gz.fernet"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy fixture ciphertext preserved")
    with pytest.raises(RuntimeError, match="require_original_key"):
        protection.repair(runtime)
    assert legacy.read_bytes() == b"legacy fixture ciphertext preserved"
    assert (runtime.ROOT / "config/backup_key_location.json").read_bytes() == original
    assert not (protection._paths(runtime) / "backup.key").exists()


def test_recovered_key_must_open_existing_latest_cipher_before_activation(runtime):
    original = (runtime.ROOT / "config/backup_key_location.json").read_bytes()
    old_key = Fernet.generate_key()
    (runtime.BASE / "backup.key").write_bytes(Fernet.generate_key())
    legacy = runtime.ROOT / "artifacts/backups/triade-legacy.db.gz.fernet"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(Fernet(old_key).encrypt(b"legacy fixture"))
    before = legacy.read_bytes()
    with pytest.raises(RuntimeError, match="key_mismatch_preserved"):
        protection.repair(runtime)
    assert (runtime.ROOT / "config/backup_key_location.json").read_bytes() == original
    assert legacy.read_bytes() == before
    assert not (protection._paths(runtime) / "backup.key").exists()


def test_status_distinguishes_actual_backend_key_from_initial_receipt(
    runtime, monkeypatch
):
    import io

    protection._json(
        runtime.WORK / "encrypted_backup_status.json",
        {
            "status": "encrypted_copy_verified",
            "backend_key_activation": "await_next_planner_cycle",
        },
    )

    def health(url, timeout):
        assert url == "http://127.0.0.1:8010/api/health"
        return io.BytesIO(
            json.dumps(
                {
                    "security": {
                        "backup_key": {
                            "configured": True,
                            "source": "file",
                            "path_exists": True,
                            "path_readable": True,
                            "path": "private fixture path not returned",
                        }
                    }
                }
            ).encode()
        )

    monkeypatch.setattr(protection.urllib.request, "urlopen", health)
    observed = protection.status(runtime)
    assert observed["backend_key_activation"] == "configured_observed"
    assert observed["copy_watcher_alive"] is False
    assert "private fixture path" not in str(observed)

"""Regression: only one owner lineage, one immutable encrypted backup key."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from triade.security.session_backup_key_vault import unlock_or_create


def _scope(root: Path, owner: str = "account-A") -> tuple[Path, Path, Path, Path]:
    db = root / "triade.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE auth_users (user_id TEXT NOT NULL)")
        con.execute("INSERT INTO auth_users VALUES (?)", (owner,))
    index = root / "active.json"
    index.write_text(
        json.dumps({"lineage": hashlib.sha256(owner.encode()).hexdigest()[:16]}),
        encoding="utf-8",
    )
    drive = root / "Drive"
    drive.mkdir()
    return db, index, drive / "vault", root / "private"


def test_identity_key_unique_reusable_and_never_plaintext_in_drive(
    tmp_path: Path,
) -> None:
    db, index, drive, local = _scope(tmp_path)
    phrase = "long unique secret recovery words"
    first = unlock_or_create(db, index, drive, local, phrase)
    second = unlock_or_create(db, index, drive, local, phrase)
    assert first["status"] == "created"
    assert second["status"] == "unlocked"
    assert first["fingerprint"] == second["fingerprint"]
    vault_text = Path(first["vault_file"]).read_text()
    assert first["vault_encrypted"]
    assert Path(first["key_local_file"]).read_text().strip() not in vault_text
    assert (Path(first["key_local_file"]).stat().st_mode & 0o777) == 0o600


def test_wrong_password_cannot_rekey(tmp_path: Path) -> None:
    db, index, drive, local = _scope(tmp_path)
    previous = unlock_or_create(db, index, drive, local, "long unique secret recovery words")
    with pytest.raises(RuntimeError, match="incorrecta"):
        unlock_or_create(db, index, drive, local, "another private recovery phrase")
    assert json.loads(Path(previous["vault_file"]).read_text())["lineage"] == previous[
        "identity_lineage"
    ]


def test_mismatched_live_bodega_blocks_identity_key(tmp_path: Path) -> None:
    db, index, drive, local = _scope(tmp_path)
    with sqlite3.connect(db) as con:
        con.execute("UPDATE auth_users SET user_id='account-B'")
    with pytest.raises(RuntimeError, match="no coincide"):
        unlock_or_create(db, index, drive, local, "long unique secret recovery words")
    assert not drive.exists()


def test_two_owner_accounts_cannot_be_silently_merged(tmp_path: Path) -> None:
    db, index, drive, local = _scope(tmp_path)
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO auth_users VALUES('account-B')")
    with pytest.raises(RuntimeError, match="sola cuenta"):
        unlock_or_create(db, index, drive, local, "long unique secret recovery words")
    assert not drive.exists()
"""The backup-key vault remains human gated and never receives prompt strings in logs."""

from __future__ import annotations

import json

import pytest

from scripts import session_backup_key_cli as cli


def _files(tmp_path, *, guarded=True, lineage="90e9a51dd7ffef31"):
    index = tmp_path / "active.json"
    index.write_text(
        json.dumps(
            {
                "lineage": lineage,
                "guard": "wal_closed_and_rows_verified_v1" if guarded else None,
            }
        ),
        encoding="utf-8",
    )
    return {
        "db": tmp_path / "not-written.sqlite3",
        "index": index,
        "drive_vault_dir": tmp_path / "vault",
        "local_private_dir": tmp_path / "private",
        "expected_lineage": lineage,
        "passphrase": "secure phrase long enough",
    }


def test_unguarded_index_never_calls_vault(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "unlock_or_create",
        lambda *args: pytest.fail("vault touched without protected index"),
    )
    with pytest.raises(RuntimeError, match="Continuidad no protegida"):
        cli.unlock(**_files(tmp_path, guarded=False))


def test_foreign_lineage_never_calls_vault(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli, "unlock_or_create", lambda *args: pytest.fail("foreign vault access")
    )
    args = _files(tmp_path)
    args["expected_lineage"] = "another-lineage"
    with pytest.raises(RuntimeError, match="Linaje no coincide"):
        cli.unlock(**args)


def test_valid_owner_returns_only_public_fingerprint(tmp_path, monkeypatch):
    calls = []

    def fake_vault(db, index, drive, local, phrase):
        calls.append(phrase)
        return {
            "status": "unlocked",
            "identity_lineage": "90e9a51dd7ffef31",
            "fingerprint": "safe-fingerprint",
            "vault_encrypted": True,
            "wrapped_key": "secret-must-not-leak",
        }

    monkeypatch.setattr(cli, "unlock_or_create", fake_vault)
    data = cli.unlock(**_files(tmp_path))
    assert calls == ["secure phrase long enough"]
    assert data["status"] == "unlocked"
    assert data["vault_encrypted"] is True
    assert "wrapped_key" not in data
    assert "secret" not in json.dumps(data)


def test_main_missing_unlock_rejects_without_tty_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli.getpass, "getpass", lambda *args: pytest.fail("prompt without consent")
    )
    paths = _files(tmp_path)
    argv = [
        "--db",
        str(paths["db"]),
        "--index",
        str(paths["index"]),
        "--drive-vault-dir",
        str(paths["drive_vault_dir"]),
        "--local-private-dir",
        str(paths["local_private_dir"]),
        "--confirm-lineage",
        paths["expected_lineage"],
    ]
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2


def test_main_non_tty_rejects_before_key_access(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(
        cli.getpass, "getpass", lambda *args: pytest.fail("insecure prompt")
    )
    paths = _files(tmp_path)
    argv = [
        "--unlock",
        "--db",
        str(paths["db"]),
        "--index",
        str(paths["index"]),
        "--drive-vault-dir",
        str(paths["drive_vault_dir"]),
        "--local-private-dir",
        str(paths["local_private_dir"]),
        "--confirm-lineage",
        paths["expected_lineage"],
    ]
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2


def test_administrative_declaration_is_visible_to_runtime_graph():
    import ast
    from pathlib import Path

    from triade.observability.code_graph import _declared_entrypoint_kind

    source = Path(cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert (
        _declared_entrypoint_kind(tree, "scripts/session_backup_key_cli.py")
        == "administrative_on_demand"
    )

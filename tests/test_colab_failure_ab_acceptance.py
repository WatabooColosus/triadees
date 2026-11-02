"""La aceptación de Colab jamás ejecuta la Bodega original en escritura."""

import hashlib
import importlib.util
import sqlite3
import subprocess
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / (
    "triade_colab_failure_ab_acceptance.py"
)
spec = importlib.util.spec_from_file_location("triade_colab_acceptance", MODULE_PATH)
assert spec is not None and spec.loader is not None
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_sqlite_copy_includes_committed_wal_without_modifying_source(tmp_path):
    path = tmp_path / "db.sqlite3"
    live = sqlite3.connect(path)
    live.execute("PRAGMA journal_mode=WAL")
    live.execute("CREATE TABLE neurons(id INTEGER PRIMARY KEY)")
    live.execute("INSERT INTO neurons VALUES (1)")
    live.commit()
    backup = tmp_path / "isolated" / "snapshot.sqlite3"
    result = audit.snapshot_sqlite(path, backup)
    assert result["quick_check"] == "ok"
    assert result["counts"] == {"neurons": 1}
    assert result["sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()
    with sqlite3.connect(backup) as conn:
        conn.execute("INSERT INTO neurons VALUES (2)")
    assert live.execute("SELECT COUNT(*) FROM neurons").fetchone()[0] == 1
    live.close()


def test_copy_refuses_symlink_and_existing_target(tmp_path):
    original = tmp_path / "original.sqlite3"
    sqlite3.connect(original).close()
    link = tmp_path / "linked.sqlite3"
    link.symlink_to(original)
    with pytest.raises(RuntimeError, match="simbólico"):
        audit.snapshot_sqlite(link, tmp_path / "copy.sqlite3")
    duplicate = tmp_path / "copy.sqlite3"
    duplicate.write_bytes(b"do-not-overwrite")
    with pytest.raises(RuntimeError, match="existe"):
        audit.snapshot_sqlite(original, duplicate)
    assert duplicate.read_bytes() == b"do-not-overwrite"


def test_wrong_commit_fails_before_accessing_bodega(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "proof").write_text("ok", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "proof"], check=True)
    subprocess.run(
        [
            "git", "-C", str(repo), "-c", "user.name=Triade Test",
            "-c", "user.email=triade@example.invalid", "commit", "-qm", "baseline",
        ],
        check=True,
    )
    bodega = tmp_path / "bodega.sqlite3"
    with pytest.raises(RuntimeError, match="commit autorizado"):
        audit.acceptance(
            bodega, repo, "a" * 40, tmp_path / "read_only_evidence.json"
        )
    assert not bodega.exists()


def test_report_is_outside_database_and_never_certifies(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "proof").write_text("ok", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "proof"], check=True)
    subprocess.run(
        [
            "git", "-C", str(repo), "-c", "user.name=Triade Test",
            "-c", "user.email=triade@example.invalid", "commit", "-qm", "baseline",
        ],
        check=True,
    )
    bodega = tmp_path / "drive" / "bodega.sqlite3"
    bodega.parent.mkdir()
    with sqlite3.connect(bodega) as conn:
        conn.execute("CREATE TABLE neurons(id INTEGER)")
        conn.execute("INSERT INTO neurons VALUES (1)")
    checksum = hashlib.sha256(bodega.read_bytes()).hexdigest()

    def mocked_probe(copy, checkout):
        assert checkout == repo
        with sqlite3.connect(copy) as conn:
            assert conn.execute("SELECT COUNT(*) FROM neurons").fetchone() == (1,)
        return {"verified_observations": 0}

    monkeypatch.setattr(audit, "inspect_copy", mocked_probe)
    with pytest.raises(RuntimeError, match="fuera de Drive"):
        audit.acceptance(bodega, repo, audit.checked_head(repo), bodega.parent / "e.json")
    evidence = audit.acceptance(
        bodega, repo, audit.checked_head(repo), tmp_path / "reports" / "e.json"
    )
    assert evidence["snapshot"]["counts"]["neurons"] == 1
    assert evidence["operational_causality_proven"] is False
    assert evidence["colab_rollback_certified"] is False
    assert evidence["promotion_authorized"] is False
    assert hashlib.sha256(bodega.read_bytes()).hexdigest() == checksum

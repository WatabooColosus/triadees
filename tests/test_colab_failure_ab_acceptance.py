"""La aceptación de Colab jamás ejecuta la Bodega original en escritura."""

import hashlib
import importlib.util
import sqlite3
import subprocess
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / ("triade_colab_failure_ab_acceptance.py")
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
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Triade Test",
            "-c",
            "user.email=triade@example.invalid",
            "commit",
            "-qm",
            "baseline",
        ],
        check=True,
    )
    bodega = tmp_path / "bodega.sqlite3"
    with pytest.raises(RuntimeError, match="commit autorizado"):
        audit.acceptance(bodega, repo, "a" * 40, tmp_path / "read_only_evidence.json")
    assert not bodega.exists()


def test_report_is_outside_database_and_never_certifies(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "proof").write_text("ok", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "proof"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Triade Test",
            "-c",
            "user.email=triade@example.invalid",
            "commit",
            "-qm",
            "baseline",
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
        audit.acceptance(
            bodega, repo, audit.checked_head(repo), bodega.parent / "e.json"
        )
    evidence = audit.acceptance(
        bodega, repo, audit.checked_head(repo), tmp_path / "reports" / "e.json"
    )
    assert evidence["snapshot"]["counts"]["neurons"] == 1
    assert evidence["operational_causality_proven"] is False
    assert evidence["colab_rollback_certified"] is False
    assert evidence["promotion_authorized"] is False
    assert hashlib.sha256(bodega.read_bytes()).hexdigest() == checksum



def test_diagnostic_explains_tasks_without_terminal_transitions(tmp_path):
    db = tmp_path / "copy.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE autonomous_tasks (task_id TEXT, status TEXT, "
            "worker_id TEXT, result_ref TEXT, lease_generation INTEGER)"
        )
        conn.executemany(
            "INSERT INTO autonomous_tasks VALUES (?, ?, ?, ?, ?)",
            [
                (str(i), "pending", "worker", None, 1)
                for i in range(5)
            ],
        )
        conn.execute(
            "CREATE TABLE autonomous_task_transitions "
            "(task_id TEXT, to_status TEXT, worker_id TEXT, "
            "result_ref TEXT, lease_generation INTEGER)"
        )
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    report = audit.diagnose_evidence_sources(db)
    assert report["table_counts"]["autonomous_tasks"] == 5
    assert report["autonomous_task_status_counts"] == {"pending": 5}
    assert report["canonical_terminal_transitions"] == 0
    assert "no_terminal_canonical_transitions" in report["diagnostic_codes"]
    assert report["production_modified"] is False
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


def test_diagnostic_separates_terminal_events_from_missing_artifacts(tmp_path):
    db = tmp_path / "copy.sqlite3"
    missing_result = tmp_path / "gone" / "result.json"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE autonomous_tasks (task_id TEXT, status TEXT, "
            "worker_id TEXT, result_ref TEXT, lease_generation INTEGER)"
        )
        conn.execute(
            "CREATE TABLE autonomous_task_transitions "
            "(task_id TEXT, to_status TEXT, worker_id TEXT, "
            "result_ref TEXT, lease_generation INTEGER)"
        )
        conn.execute(
            "INSERT INTO autonomous_tasks VALUES (?, ?, ?, ?, ?)",
            ("real-1", "failed", "worker", str(missing_result), 1),
        )
        conn.execute(
            "INSERT INTO autonomous_task_transitions VALUES (?, ?, ?, ?, ?)",
            ("real-1", "failed", "worker", str(missing_result), 1),
        )
    report = audit.diagnose_evidence_sources(db)
    assert report["canonical_terminal_transitions"] == 1
    assert report["canonical_artifact_sample"]["nonempty_result_refs"] == 1
    assert report["canonical_artifact_sample"]["accessible_result_json"] == 0
    assert "result_artifacts_not_accessible_in_this_colab" in report[
        "diagnostic_codes"
    ]
    assert report["canonical_artifacts_fully_verified"] is False
    assert report["production_modified"] is False

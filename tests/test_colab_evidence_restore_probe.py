"""Restore proof tests use synthetic isolated receipts, never production data."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from tools import triade_colab_evidence_continuity as agent
from tools.triade_colab_evidence_restore_probe import prove_isolated_restore


def _fixture(tmp_path: Path) -> Path:
    runtime = tmp_path / "source_runtime"
    runtime.mkdir()
    ref = "runs/background/test-session/tasks/task-100/result.json"
    dest = runtime / Path(ref).parent
    dest.mkdir(parents=True)
    raw = b'{"status":"failed","message":"fixture_only"}'
    file_hash = hashlib.sha256(raw).hexdigest()
    (dest / "result.json").write_bytes(raw)
    (dest / "manifest.json").write_text(
        json.dumps(
            {
                "task_id": "task-100",
                "task_type": "synthetic_unit_fixture",
                "status": "failed",
                "worker_id": "worker-test",
                "lease_generation": 1,
                "result_hash": file_hash,
                "artifact_hashes": {"result.json": file_hash},
            }
        ),
        encoding="utf-8",
    )
    db = tmp_path / "fixture.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE autonomous_tasks (task_id TEXT, task_type TEXT, "
            "status TEXT, worker_id TEXT, lease_generation INTEGER, "
            "result_ref TEXT, updated_at TEXT)"
        )
        conn.execute(
            "INSERT INTO autonomous_tasks VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "task-100",
                "synthetic_unit_fixture",
                "failed",
                "worker-test",
                1,
                ref,
                "2026-11-01T00:00:00Z",
            ),
        )
    store = tmp_path / "private_archive"
    store.mkdir()
    assert agent.archive(db, runtime, store)["archived"] == 1
    return store


def test_restore_real_hash_contract_in_isolation(tmp_path):
    store = _fixture(tmp_path)
    temp_base = tmp_path / "scratch"
    temp_base.mkdir()
    original = {p: p.read_bytes() for p in store.rglob("*") if p.is_file()}
    report = prove_isolated_restore(agent, store, temp_base=temp_base)
    assert report["restore"]["restored"] == 1
    assert report["repeat_restore"]["already_present"] == 1
    assert report["tamper_rejection"]["invalid_receipts"] == 1
    assert report["verified_file_count"] == 2
    assert report["promotion_authorized"] is False
    assert report["colab_restart_restoration_certified"] is False
    assert original == {p: p.read_bytes() for p in store.rglob("*") if p.is_file()}


def test_archive_inside_scratch_disallowed(tmp_path):
    store = _fixture(tmp_path)
    with pytest.raises(RuntimeError, match="isolation_boundary_invalid"):
        prove_isolated_restore(agent, store, temp_base=tmp_path)


def test_symlink_archive_disallowed(tmp_path):
    store = _fixture(tmp_path)
    symlink = tmp_path / "alias"
    symlink.symlink_to(store, target_is_directory=True)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(RuntimeError, match="unsafe_archive_store"):
        prove_isolated_restore(agent, symlink, temp_base=scratch)


def test_empty_archive_disallowed(tmp_path):
    store = tmp_path / "empty"
    (store / "items").mkdir(parents=True)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(RuntimeError, match="no_valid_canonical_receipt"):
        prove_isolated_restore(agent, store, temp_base=scratch)

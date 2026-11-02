"""Session-bound restore certification: synthetic fixtures only, no Colab DB writes."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

ROOT = Path(__file__).parent
agent = _load(ROOT / "triade_colab_evidence_continuity.py", "evidence_v1")
cert = _load(ROOT / "triade_colab_cross_session_cert.py", "cross_cert_v1")
A = "1" * 32
B = "2" * 32


def _fixture(tmp_path):
    runtime = tmp_path / "runtimeA"
    runtime.mkdir()
    store = tmp_path / "store"
    store.mkdir()
    rel = Path("runs/background/20261102-a/tasks/task-1/result.json")
    p = runtime / rel.parent
    p.mkdir(parents=True)
    raw = b'{"status":"failed","message":"fixture_only"}'
    sha = hashlib.sha256(raw).hexdigest()
    (p / "result.json").write_bytes(raw)
    (p / "manifest.json").write_text(json.dumps({"task_id": "task-1", "task_type": "unit_fixture", "status": "failed", "worker_id": "worker-test", "lease_generation": 1, "result_hash": sha, "artifact_hashes": {"result.json": sha}}))
    db = tmp_path / "snapshot.sqlite3"
    with sqlite3.connect(db) as cx:
        cx.execute("CREATE TABLE autonomous_tasks(task_id TEXT, task_type TEXT, status TEXT, worker_id TEXT, lease_generation INTEGER, result_ref TEXT, updated_at TEXT)")
        cx.execute("INSERT INTO autonomous_tasks VALUES(?,?,?,?,?,?,?)", ("task-1", "unit_fixture", "failed", "worker-test", 1, rel.as_posix(), "2026-11-02"))
    assert agent.archive(db, runtime, store)["archived"] == 1
    return runtime, store, rel, db


def test_no_prior_marker_keeps_gate_closed(tmp_path):
    runtime, store, _ref, _db = _fixture(tmp_path)
    pre = cert.prepare(agent, runtime, store, A)
    result = cert.complete(agent, runtime, store, A, pre, {"status": "ok", "restored": 0})
    assert result["status"] == "same_session_or_no_prior_baseline"
    assert result["anchor_saved"]
    assert not result["cross_session_restoration_certified"]


def test_new_runtime_restores_genuine_saved_fixture(tmp_path):
    runtime, store, rel, db = _fixture(tmp_path)
    original = db.read_bytes()
    cert.complete(agent, runtime, store, A, cert.prepare(agent, runtime, store, A), {"status": "ok", "restored": 0})
    new = tmp_path / "runtimeB"
    new.mkdir()
    before = cert.prepare(agent, new, store, B)
    assert before["prior_refs_missing_before_restore"] == [rel.as_posix()]
    restored = agent.restore(new, store)
    result = cert.complete(agent, new, store, B, before, restored)
    assert result["cross_session_restoration_certified"]
    assert result["verified_recovered_refs"] == 1
    assert (new / rel).read_bytes() == (runtime / rel).read_bytes()
    assert db.read_bytes() == original
    again = cert.prepare(agent, new, store, B)
    repeat = cert.complete(agent, new, store, B, again, agent.restore(new, store))
    assert repeat["cross_session_restoration_certified"] is False


def test_same_runtime_never_certified(tmp_path):
    runtime, store, _rel, _db = _fixture(tmp_path)
    cert.complete(agent, runtime, store, A, cert.prepare(agent, runtime, store, A), {"status": "ok", "restored": 0})
    pre = cert.prepare(agent, runtime, store, A)
    assert pre["prior_session"] is None
    o = cert.complete(agent, runtime, store, A, pre, {"status": "ok", "restored": 1})
    assert not o["cross_session_restoration_certified"]


def test_no_actual_restoration_cannot_certify(tmp_path):
    runtime, store, _rel, _db = _fixture(tmp_path)
    cert.complete(agent, runtime, store, A, cert.prepare(agent, runtime, store, A), {"status": "ok", "restored": 0})
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    before = cert.prepare(agent, fresh, store, B)
    o = cert.complete(agent, fresh, store, B, before, {"status": "ok", "restored": 7})
    assert not o["cross_session_restoration_certified"]
    assert o["verified_recovered_refs"] == 0


def test_corruption_in_private_receipt_does_not_certify(tmp_path):
    runtime, store, _rel, _db = _fixture(tmp_path)
    cert.complete(agent, runtime, store, A, cert.prepare(agent, runtime, store, A), {"status": "ok", "restored": 0})
    (next((store / "items").glob("*/*")) / "result.json").write_bytes(b"forged")
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    before = cert.prepare(agent, fresh, store, B)
    assert before["prior_anchors_verified"] == 0
    restored = agent.restore(fresh, store)
    assert restored["invalid_receipts"] == 1
    result = cert.complete(agent, fresh, store, B, before, restored)
    assert not result["cross_session_restoration_certified"]


def test_runtime_identity_is_reused_and_symlink_rejected(tmp_path):
    x = tmp_path / "identity.txt"
    token = cert.runtime_identity(x)
    assert cert.runtime_identity(x) == token
    assert len(token) == 32
    link = tmp_path / "alias"
    link.symlink_to(x)
    with pytest.raises(RuntimeError, match="unsafe_runtime_identity_path"):
        cert.runtime_identity(link)

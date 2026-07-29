from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from triade.runtime.task_artifacts import AtomicArtifactWriter, CanonicalTaskArtifacts
from triade.runtime.task_leases import AutonomousTaskStore


def _finalize(tmp_path: Path, task_id: str = "task-real") -> CanonicalTaskArtifacts:
    artifacts = CanonicalTaskArtifacts(tmp_path / "run-1", task_id)
    artifacts.finalize(
        task={"task_id": task_id, "task_type": "pulse_check", "created_at": "now"},
        execution={"evidence": [], "resource_usage": {}, "postconditions": {}},
        result={"status": "observed"},
        worker_id="worker-1",
        lease_generation=1,
        payload_hash="abc",
        status="observed",
    )
    return artifacts


def test_v2_task_never_uses_none_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="canonical_task_id_required"):
        CanonicalTaskArtifacts(tmp_path, "None")
    artifacts = _finalize(tmp_path)
    assert "task-None" not in str(artifacts.path)


def test_result_ref_exists_before_completion(tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    store = AutonomousTaskStore(db_path)
    task = store.enqueue("pulse_check", {}, idempotency_key="artifact")
    claimed = store.claim("worker")
    assert claimed
    result_ref = _finalize(tmp_path, task["task_id"]).path / "result.json"
    assert result_ref.is_file()
    assert store.complete(
        task["task_id"], "worker", claimed["lease_generation"], str(result_ref)
    )


def test_manifest_hashes_match_files(tmp_path: Path) -> None:
    artifacts = _finalize(tmp_path)
    manifest = json.loads(
        (artifacts.path / "manifest.json").read_text(encoding="utf-8")
    )
    for name, expected in manifest["artifact_hashes"].items():
        assert CanonicalTaskArtifacts.sha256(artifacts.path / name) == expected
    artifacts.verify()


def test_atomic_write_survives_interruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "result.json"
    AtomicArtifactWriter.write_bytes(target, b"old")

    def interrupted(_source: Path, _target: Path) -> None:
        raise OSError("injected_interruption")

    monkeypatch.setattr(os, "replace", interrupted)
    with pytest.raises(OSError, match="injected_interruption"):
        AtomicArtifactWriter.write_bytes(target, b"new")
    assert target.read_bytes() == b"old"


def test_missing_artifact_prevents_completion(tmp_path: Path) -> None:
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("pulse_check", {}, idempotency_key="missing")
    claimed = store.claim("worker")
    assert claimed
    assert not store.complete(
        task["task_id"],
        "worker",
        claimed["lease_generation"],
        str(tmp_path / "missing.json"),
    )
    assert store.get(task["task_id"])["status"] == "leased"


def test_legacy_id_is_metadata_only(tmp_path: Path) -> None:
    artifacts = _finalize(tmp_path, "task-v2")
    assert artifacts.path == tmp_path / "run-1" / "tasks" / "task-v2"

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from triade.runtime.effect_receipt import EffectReceipt
from triade.runtime.execution_result import ExecutionResult
from triade.workers.worker_loop import WorkerLoop


def test_completed_requires_effect_receipt() -> None:
    with pytest.raises(
        ValidationError, match="completed_requires_verified_effect_receipt"
    ):
        ExecutionResult(
            status="completed",
            executed=True,
            evidence=["result.json"],
            observation_justification="observation",
        )


def test_failed_postcondition_prevents_completion() -> None:
    receipt = EffectReceipt(
        action="write",
        target="x",
        verified=False,
        verifier="file",
        postcondition={"passed": False},
    )
    with pytest.raises(
        ValidationError, match="completed_requires_verified_effect_receipt"
    ):
        ExecutionResult(
            status="completed",
            executed=True,
            evidence=["x"],
            observation_justification="checked",
            effect_receipt=receipt,
        )


def test_file_effect_verified_by_hash(tmp_path: Path) -> None:
    target = tmp_path / "created.txt"
    target.write_text("real", encoding="utf-8")
    expected = hashlib.sha256(b"real").hexdigest()
    receipt = EffectReceipt.verify_file(target, expected)
    assert receipt.verified
    assert receipt.postcondition["sha256"] == expected


def test_install_effect_requires_health_check(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.json"
    inventory.write_text("{}", encoding="utf-8")
    missing = EffectReceipt.verify_install(
        model="local",
        inventory_ref=str(inventory),
        health_ref=str(tmp_path / "missing"),
    )
    assert not missing.verified
    health = tmp_path / "health.json"
    health.write_text('{"ok":true}', encoding="utf-8")
    assert EffectReceipt.verify_install(
        model="local", inventory_ref=str(inventory), health_ref=str(health)
    ).verified


def test_backup_requires_restore_test(tmp_path: Path) -> None:
    backup = tmp_path / "backup.enc"
    backup.write_bytes(b"encrypted")
    assert not EffectReceipt.verify_backup(
        backup_ref=str(backup),
        hash_matches=True,
        restore_test_ref=str(tmp_path / "missing-restore.json"),
    ).verified
    restore = tmp_path / "restore.json"
    restore.write_text('{"restored":true}', encoding="utf-8")
    assert EffectReceipt.verify_backup(
        backup_ref=str(backup), hash_matches=True, restore_test_ref=str(restore)
    ).verified


def test_research_completion_requires_sources(tmp_path: Path) -> None:
    result_ref = tmp_path / "result.json"
    result_ref.write_text("{}", encoding="utf-8")
    result = WorkerLoop._canonical_execution_result(
        {"status": "candidate_created", "candidate_id": "candidate-1"},
        str(result_ref),
    )
    assert result.status == "failed"
    assert result.error_code == "verified_effect_receipt_missing"
    receipt = EffectReceipt.verify_research(
        question="q",
        source_refs=["https://primary.example/a", "https://other.example/b"],
    )
    assert receipt.verified
    assert receipt.postcondition["consolidated"] is False

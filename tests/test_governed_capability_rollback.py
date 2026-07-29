from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from triade.runtime.effect_receipt import EffectReceipt
from triade.runtime.governed_capability import (
    CapabilityLifecycle,
    GovernedFileWriteCapability,
    GovernedSQLiteValueCapability,
)


class FailingPostconditionFile(GovernedFileWriteCapability):
    def verify(self) -> EffectReceipt:
        return EffectReceipt(
            action="write_file", target=str(self.target),
            postcondition={"passed": False}, verified=False,
            verifier="injected_failure",
        )


class FailingRollbackFile(FailingPostconditionFile):
    def verify_rollback(self) -> EffectReceipt:
        return EffectReceipt(
            action="rollback_file", target=str(self.target),
            postcondition={"passed": False}, verified=False,
            verifier="injected_rollback_failure",
        )


class IrreversibleFile(GovernedFileWriteCapability):
    irreversible = True
    approval_level = "human"


def test_file_action_can_rollback(tmp_path: Path) -> None:
    target = tmp_path / "config.txt"
    target.write_text("before", encoding="utf-8")
    capability = GovernedFileWriteCapability(target, "after", tmp_path / "evidence")
    capability.prepare()
    capability.execute()
    assert capability.verify().verified
    capability.rollback()
    assert capability.verify_rollback().verified
    assert target.read_text(encoding="utf-8") == "before"


def test_db_action_can_rollback(tmp_path: Path) -> None:
    capability = GovernedSQLiteValueCapability(
        tmp_path / "db.sqlite", "mode", "active", tmp_path / "evidence"
    )
    capability.prepare()
    capability.execute()
    assert capability.verify().verified
    capability.rollback()
    assert capability.verify_rollback().verified


def test_failed_postcondition_triggers_rollback(tmp_path: Path) -> None:
    target = tmp_path / "new.txt"
    result = CapabilityLifecycle().run(
        FailingPostconditionFile(target, "content", tmp_path / "evidence")
    )
    assert result.status == "rolled_back"
    assert not target.exists()
    assert result.rollback_receipt and result.rollback_receipt.verified


def test_failed_rollback_escalates(tmp_path: Path) -> None:
    result = CapabilityLifecycle().run(
        FailingRollbackFile(tmp_path / "new.txt", "content", tmp_path / "evidence")
    )
    assert result.status == "rollback_failed"
    assert result.escalated


def test_irreversible_action_requires_approval(tmp_path: Path) -> None:
    target = tmp_path / "irreversible.txt"
    capability = IrreversibleFile(target, "content", tmp_path / "evidence")
    result = CapabilityLifecycle().run(capability)
    assert result.status == "blocked"
    assert not target.exists()
    approved = CapabilityLifecycle().run(capability, human_approved=True)
    assert approved.status == "completed"


def test_rollback_claim_requires_test_evidence() -> None:
    with pytest.raises(ValidationError, match="verified_effect_requires_evidence"):
        EffectReceipt(
            action="rollback", target="x", postcondition={"passed": True},
            verified=True, verifier="self_claim", evidence_refs=[],
        )

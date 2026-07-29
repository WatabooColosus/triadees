"""Verified postcondition receipts for governed effects and observations."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator


class EffectReceipt(BaseModel):
    action: str
    target: str
    precondition: dict[str, Any] = Field(default_factory=dict)
    execution: dict[str, Any] = Field(default_factory=dict)
    postcondition: dict[str, Any] = Field(default_factory=dict)
    verified: bool
    verifier: str
    evidence_refs: list[str] = Field(default_factory=list)
    rollback_ref: str | None = None
    rollback_required: bool = False
    irreversible: bool = False
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @model_validator(mode="after")
    def require_verification_evidence(self) -> EffectReceipt:
        if self.verified:
            if self.postcondition.get("passed") is not True:
                raise ValueError("verified_effect_requires_passing_postcondition")
            if not self.evidence_refs:
                raise ValueError("verified_effect_requires_evidence")
            if not self.verifier.strip():
                raise ValueError("verified_effect_requires_verifier")
            if self.rollback_required and not self.rollback_ref:
                raise ValueError("reversible_effect_requires_rollback_ref")
            if self.rollback_required and self.irreversible:
                raise ValueError("effect_cannot_be_reversible_and_irreversible")
        return self

    @classmethod
    def verify_file(
        cls,
        path: str | Path,
        expected_sha256: str,
        *,
        rollback_ref: str | None = None,
        rollback_required: bool = False,
    ) -> EffectReceipt:
        target = Path(path)
        exists = target.is_file()
        actual = hashlib.sha256(target.read_bytes()).hexdigest() if exists else None
        passed = exists and actual == expected_sha256
        return cls(
            action="write_file",
            target=str(target),
            execution={"expected_sha256": expected_sha256},
            postcondition={"passed": passed, "exists": exists, "sha256": actual},
            verified=passed,
            verifier="sha256_file_verifier",
            evidence_refs=[str(target)] if exists else [],
            rollback_ref=rollback_ref,
            rollback_required=rollback_required,
        )

    @classmethod
    def verify_command(
        cls, *, command_id: str, exit_code: int, stdout_ref: str, stderr_ref: str
    ) -> EffectReceipt:
        refs = [ref for ref in (stdout_ref, stderr_ref) if Path(ref).is_file()]
        passed = exit_code == 0 and len(refs) == 2
        return cls(
            action="execute_command",
            target=command_id,
            execution={"exit_code": exit_code},
            postcondition={"passed": passed},
            verified=passed,
            verifier="exit_code_and_log_verifier",
            evidence_refs=refs,
        )

    @classmethod
    def verify_install(
        cls, *, model: str, inventory_ref: str, health_ref: str
    ) -> EffectReceipt:
        refs = [ref for ref in (inventory_ref, health_ref) if Path(ref).is_file()]
        passed = len(refs) == 2
        return cls(
            action="install_model",
            target=model,
            postcondition={"passed": passed, "inventory": bool(refs)},
            verified=passed,
            verifier="inventory_and_health_verifier",
            evidence_refs=refs,
        )

    @classmethod
    def verify_backup(
        cls, *, backup_ref: str, hash_matches: bool, restore_test_ref: str
    ) -> EffectReceipt:
        refs = [ref for ref in (backup_ref, restore_test_ref) if Path(ref).is_file()]
        passed = hash_matches and len(refs) == 2
        return cls(
            action="backup",
            target=backup_ref,
            postcondition={
                "passed": passed,
                "hash_matches": hash_matches,
                "restore_test": len(refs) == 2,
            },
            verified=passed,
            verifier="backup_restore_verifier",
            evidence_refs=refs,
            rollback_ref=restore_test_ref if passed else None,
        )

    @classmethod
    def verify_research(cls, *, question: str, source_refs: list[str]) -> EffectReceipt:
        valid = [
            ref
            for ref in source_refs
            if ref.startswith(("http://", "https://", "doi:"))
        ]
        passed = len(valid) >= 2
        return cls(
            action="research",
            target=question,
            postcondition={
                "passed": passed,
                "source_count": len(valid),
                "consolidated": False,
            },
            verified=passed,
            verifier="research_source_reference_verifier",
            evidence_refs=valid,
        )

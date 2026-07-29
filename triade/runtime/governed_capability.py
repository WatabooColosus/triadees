"""Lifecycle contract for effectful capabilities with verified rollback."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from triade.runtime.effect_receipt import EffectReceipt
from triade.runtime.task_artifacts import AtomicArtifactWriter


class GovernedCapability(ABC):
    irreversible = False
    approval_level = "none"

    @abstractmethod
    def prepare(self) -> dict[str, Any]: ...

    @abstractmethod
    def execute(self) -> dict[str, Any]: ...

    @abstractmethod
    def verify(self) -> EffectReceipt: ...

    @abstractmethod
    def rollback(self) -> dict[str, Any]: ...

    @abstractmethod
    def verify_rollback(self) -> EffectReceipt: ...


@dataclass(frozen=True, slots=True)
class CapabilityLifecycleResult:
    status: str
    effect_receipt: EffectReceipt | None = None
    rollback_receipt: EffectReceipt | None = None
    escalated: bool = False
    reason: str = ""


class CapabilityLifecycle:
    def run(
        self, capability: GovernedCapability, *, human_approved: bool = False
    ) -> CapabilityLifecycleResult:
        if capability.irreversible and not human_approved:
            return CapabilityLifecycleResult(
                "blocked", reason="irreversible_action_requires_human_approval"
            )
        capability.prepare()
        capability.execute()
        receipt = capability.verify()
        if receipt.verified:
            return CapabilityLifecycleResult("completed", effect_receipt=receipt)
        capability.rollback()
        rollback = capability.verify_rollback()
        if rollback.verified:
            return CapabilityLifecycleResult(
                "rolled_back", effect_receipt=receipt, rollback_receipt=rollback,
                reason="postcondition_failed",
            )
        return CapabilityLifecycleResult(
            "rollback_failed", effect_receipt=receipt, rollback_receipt=rollback,
            escalated=True, reason="rollback_verification_failed",
        )


class GovernedFileWriteCapability(GovernedCapability):
    def __init__(
        self, target: str | Path, content: str, workspace: str | Path,
        authorized_root: str | Path | None = None,
    ) -> None:
        self.target = Path(target)
        self.content = content
        self.workspace = Path(workspace)
        self.backup_ref: Path | None = None
        self.rollback_target: Path | None = None
        self.existed = False
        self.authorized_root = Path(authorized_root).resolve() if authorized_root else None

    def prepare(self) -> dict[str, Any]:
        if self.authorized_root and not self.target.resolve().is_relative_to(self.authorized_root):
            raise PermissionError("target_outside_authorized_root")
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.existed = self.target.is_file()
        if self.existed:
            self.backup_ref = self.workspace / f"backup-{uuid4().hex}.bin"
            AtomicArtifactWriter.write_bytes(self.backup_ref, self.target.read_bytes())
        return {"existed": self.existed, "backup_ref": str(self.backup_ref or "")}

    def rollback_spec(self) -> dict[str, Any]:
        return {
            "target": str(self.target), "existed": self.existed,
            "backup_ref": str(self.backup_ref or ""), "workspace": str(self.workspace),
        }

    @staticmethod
    def rollback_from_spec(spec: dict[str, Any]) -> EffectReceipt:
        target = Path(str(spec["target"]))
        workspace = Path(str(spec["workspace"]))
        existed = bool(spec.get("existed"))
        backup = Path(str(spec.get("backup_ref") or ""))
        if existed and backup.is_file():
            AtomicArtifactWriter.write_bytes(target, backup.read_bytes())
            passed = target.is_file() and target.read_bytes() == backup.read_bytes()
            refs = [str(target), str(backup)] if passed else []
            rollback_ref = str(backup)
        elif not existed and target.exists():
            trash = workspace / "trash"
            trash.mkdir(parents=True, exist_ok=True)
            moved = trash / f"{target.name}-{uuid4().hex}"
            shutil.move(str(target), moved)
            passed = not target.exists() and moved.is_file()
            refs = [str(moved)] if passed else []
            rollback_ref = str(moved)
        else:
            passed, refs, rollback_ref = not existed and not target.exists(), [], ""
        return EffectReceipt(
            action="rollback_file", target=str(target),
            postcondition={"passed": passed}, verified=passed,
            verifier="serialized_file_rollback_verifier", evidence_refs=refs,
            rollback_ref=rollback_ref or None,
        )

    def execute(self) -> dict[str, Any]:
        AtomicArtifactWriter.write_bytes(self.target, self.content.encode())
        return {"target": str(self.target)}

    def verify(self) -> EffectReceipt:
        expected = hashlib.sha256(self.content.encode()).hexdigest()
        return EffectReceipt.verify_file(self.target, expected)

    def rollback(self) -> dict[str, Any]:
        if self.existed and self.backup_ref:
            AtomicArtifactWriter.write_bytes(self.target, self.backup_ref.read_bytes())
            self.rollback_target = self.backup_ref
        elif self.target.exists():
            trash = self.workspace / "trash"
            trash.mkdir(parents=True, exist_ok=True)
            self.rollback_target = trash / f"{self.target.name}-{uuid4().hex}"
            shutil.move(str(self.target), self.rollback_target)
        return {"rollback_target": str(self.rollback_target or "")}

    def verify_rollback(self) -> EffectReceipt:
        if self.existed and self.backup_ref:
            passed = self.target.is_file() and self.target.read_bytes() == self.backup_ref.read_bytes()
            refs = [str(self.target), str(self.backup_ref)] if passed else []
        else:
            passed = not self.target.exists() and bool(
                self.rollback_target and self.rollback_target.is_file()
            )
            refs = [str(self.rollback_target)] if passed and self.rollback_target else []
        return EffectReceipt(
            action="rollback_file", target=str(self.target),
            postcondition={"passed": passed}, verified=passed,
            verifier="file_rollback_verifier", evidence_refs=refs,
            rollback_ref=str(self.rollback_target or "") or None,
        )


class GovernedSQLiteValueCapability(GovernedCapability):
    def __init__(self, db_path: str | Path, key: str, value: str, evidence_dir: str | Path) -> None:
        self.db_path = Path(db_path)
        self.key = key
        self.value = value
        self.evidence_dir = Path(evidence_dir)
        self.previous: str | None = None

    def prepare(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS governed_kv(key TEXT PRIMARY KEY,value TEXT)")
            row = conn.execute("SELECT value FROM governed_kv WHERE key=?", (self.key,)).fetchone()
        self.previous = str(row[0]) if row else None
        return {"previous": self.previous}

    def execute(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO governed_kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (self.key, self.value),
            )
        return {"key": self.key}

    def _value(self) -> str | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT value FROM governed_kv WHERE key=?", (self.key,)).fetchone()
        return str(row[0]) if row else None

    def _evidence(self, name: str, value: Any) -> str:
        target = self.evidence_dir / name
        AtomicArtifactWriter.write_json(target, value)
        return str(target)

    def verify(self) -> EffectReceipt:
        current = self._value()
        passed = current == self.value
        ref = self._evidence("db-effect.json", {"key": self.key, "value": current})
        return EffectReceipt(
            action="sqlite_write", target=self.key, postcondition={"passed": passed},
            verified=passed, verifier="sqlite_readback_verifier", evidence_refs=[ref] if passed else [],
        )

    def rollback(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            if self.previous is None:
                conn.execute("DELETE FROM governed_kv WHERE key=?", (self.key,))
            else:
                conn.execute("UPDATE governed_kv SET value=? WHERE key=?", (self.previous, self.key))
        return {"restored": self.previous}

    def verify_rollback(self) -> EffectReceipt:
        current = self._value()
        passed = current == self.previous
        ref = self._evidence("db-rollback.json", {"key": self.key, "value": current})
        return EffectReceipt(
            action="rollback_sqlite", target=self.key, postcondition={"passed": passed},
            verified=passed, verifier="sqlite_rollback_readback", evidence_refs=[ref] if passed else [],
            rollback_ref=ref if passed else None,
        )

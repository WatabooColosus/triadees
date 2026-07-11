"""Rollback ejecutable y auditable para capacidades protegidas."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from triade.core.contracts import utc_now

RollbackStatus = Literal["planned", "applied", "failed", "rejected"]
RollbackHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class RollbackPlan:
    rollback_id: str
    capability: str
    candidate_id: str
    report_id: str
    target_subject_id: str
    target_evaluation_id: str
    suite_id: str
    suite_version: str
    reason: str
    requested_by: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RollbackResult:
    rollback_id: str
    capability: str
    status: RollbackStatus
    before_state: dict[str, Any]
    after_state: dict[str, Any]
    error: str | None
    applied_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RollbackExecutor:
    """Ejecuta rollback solo mediante handlers explícitamente registrados."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._handlers: dict[str, RollbackHandler] = {}
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS rollback_operations (
                    rollback_id TEXT PRIMARY KEY,
                    capability TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    report_id TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    before_state_json TEXT NOT NULL DEFAULT '{}',
                    after_state_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    requested_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    applied_at TEXT
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rollback_capability_status "
                "ON rollback_operations(capability, status)"
            )

    def register_handler(self, capability: str, handler: RollbackHandler) -> None:
        clean = capability.strip()
        if not clean:
            raise ValueError("capability es obligatorio")
        if clean in self._handlers:
            raise ValueError(f"Ya existe rollback handler para capability={clean}")
        self._handlers[clean] = handler

    def plan(
        self,
        *,
        rollback_id: str,
        capability: str,
        candidate_id: str,
        report_id: str,
        target: dict[str, Any],
        reason: str,
        requested_by: str,
    ) -> RollbackPlan:
        required = {
            "subject_id",
            "evaluation_id",
            "suite_id",
            "suite_version",
        }
        missing = required.difference(target)
        if missing:
            raise ValueError(f"rollback target incompleto: {sorted(missing)}")
        if not all(
            value.strip()
            for value in (rollback_id, capability, candidate_id, report_id, reason, requested_by)
        ):
            raise ValueError("los campos textuales del rollback son obligatorios")
        plan = RollbackPlan(
            rollback_id=rollback_id,
            capability=capability,
            candidate_id=candidate_id,
            report_id=report_id,
            target_subject_id=str(target["subject_id"]),
            target_evaluation_id=str(target["evaluation_id"]),
            suite_id=str(target["suite_id"]),
            suite_version=str(target["suite_version"]),
            reason=reason,
            requested_by=requested_by,
            created_at=utc_now(),
        )
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO rollback_operations
                (rollback_id, capability, candidate_id, report_id, plan_json,
                 status, requested_by, created_at)
                VALUES (?, ?, ?, ?, ?, 'planned', ?, ?)""",
                (
                    rollback_id,
                    capability,
                    candidate_id,
                    report_id,
                    json.dumps(plan.to_dict(), ensure_ascii=False, sort_keys=True),
                    requested_by,
                    plan.created_at,
                ),
            )
        return plan

    def execute(self, rollback_id: str) -> RollbackResult:
        plan = self.get_plan(rollback_id)
        if plan is None:
            raise KeyError(f"No existe rollback plan: {rollback_id}")
        current = self.get_result(rollback_id)
        if current and current.status == "applied":
            return current
        handler = self._handlers.get(plan.capability)
        if handler is None:
            return self._record_result(
                plan,
                status="rejected",
                before_state={},
                after_state={},
                error=f"No existe rollback handler para capability={plan.capability}",
            )
        request = {
            "rollback_id": plan.rollback_id,
            "capability": plan.capability,
            "candidate_id": plan.candidate_id,
            "report_id": plan.report_id,
            "target": {
                "subject_id": plan.target_subject_id,
                "evaluation_id": plan.target_evaluation_id,
                "suite_id": plan.suite_id,
                "suite_version": plan.suite_version,
            },
            "reason": plan.reason,
            "requested_by": plan.requested_by,
        }
        try:
            response = handler(request)
            before_state = dict(response.get("before_state") or {})
            after_state = dict(response.get("after_state") or {})
            applied = bool(response.get("applied"))
            if not applied:
                return self._record_result(
                    plan,
                    status="failed",
                    before_state=before_state,
                    after_state=after_state,
                    error=str(response.get("error") or "handler no confirmó aplicación"),
                )
            if str(after_state.get("subject_id")) != plan.target_subject_id:
                return self._record_result(
                    plan,
                    status="failed",
                    before_state=before_state,
                    after_state=after_state,
                    error="estado restaurado no coincide con target_subject_id",
                )
            return self._record_result(
                plan,
                status="applied",
                before_state=before_state,
                after_state=after_state,
                error=None,
            )
        except Exception as exc:  # noqa: BLE001 - la auditoría debe capturar el fallo
            return self._record_result(
                plan,
                status="failed",
                before_state={},
                after_state={},
                error=f"{type(exc).__name__}: {exc}",
            )

    def _record_result(
        self,
        plan: RollbackPlan,
        *,
        status: RollbackStatus,
        before_state: dict[str, Any],
        after_state: dict[str, Any],
        error: str | None,
    ) -> RollbackResult:
        applied_at = utc_now()
        with self._connect() as conn:
            conn.execute(
                """UPDATE rollback_operations SET
                    status=?, before_state_json=?, after_state_json=?, error=?, applied_at=?
                WHERE rollback_id=?""",
                (
                    status,
                    json.dumps(before_state, ensure_ascii=False, sort_keys=True),
                    json.dumps(after_state, ensure_ascii=False, sort_keys=True),
                    error,
                    applied_at,
                    plan.rollback_id,
                ),
            )
        return RollbackResult(
            rollback_id=plan.rollback_id,
            capability=plan.capability,
            status=status,
            before_state=before_state,
            after_state=after_state,
            error=error,
            applied_at=applied_at,
        )

    def get_plan(self, rollback_id: str) -> RollbackPlan | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT plan_json FROM rollback_operations WHERE rollback_id = ?",
                (rollback_id,),
            ).fetchone()
        return RollbackPlan(**json.loads(row["plan_json"])) if row else None

    def get_result(self, rollback_id: str) -> RollbackResult | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM rollback_operations WHERE rollback_id = ?",
                (rollback_id,),
            ).fetchone()
        if row is None or row["status"] == "planned":
            return None
        return RollbackResult(
            rollback_id=str(row["rollback_id"]),
            capability=str(row["capability"]),
            status=str(row["status"]),
            before_state=json.loads(row["before_state_json"] or "{}"),
            after_state=json.loads(row["after_state_json"] or "{}"),
            error=row["error"],
            applied_at=str(row["applied_at"]),
        )

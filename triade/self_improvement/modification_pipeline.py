"""Automodificación: test primero, parche limitado, CI completo,
mutación, canary, autofusión en verde, rollback automático.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from triade.core.contracts import utc_now

ModificationPhase = Literal[
    "proposed", "test_first", "patch_limited", "ci_running",
    "mutation_testing", "canary", "auto_merge_green", "rollback",
    "completed", "rejected",
]


@dataclass(frozen=True, slots=True)
class ModificationProposal:
    proposal_id: str
    target_file: str
    description: str
    risk_level: str
    test_required: bool
    ci_required: bool
    canary_required: bool
    rollback_required: bool
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ModificationPhaseRecord:
    proposal_id: str
    phase: ModificationPhase
    status: str
    details: dict[str, Any]
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CanaryObservation:
    canary_id: str
    proposal_id: str
    metric_name: str
    baseline_value: float
    canary_value: float
    delta: float
    passed: bool
    observed_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PHASE_ORDER: list[ModificationPhase] = [
    "proposed", "test_first", "patch_limited", "ci_running",
    "mutation_testing", "canary", "auto_merge_green", "completed",
]


class SelfModificationPipeline:
    """Pipeline completo de automodificación con todas las salvaguardas."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS modification_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    target_file TEXT NOT NULL,
                    description TEXT NOT NULL,
                    risk_level TEXT NOT NULL DEFAULT 'medium',
                    test_required INTEGER NOT NULL DEFAULT 1,
                    ci_required INTEGER NOT NULL DEFAULT 1,
                    canary_required INTEGER NOT NULL DEFAULT 1,
                    rollback_required INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS modification_phases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proposal_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    status TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    recorded_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS canary_observations (
                    canary_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    baseline_value REAL NOT NULL,
                    canary_value REAL NOT NULL,
                    delta REAL NOT NULL,
                    passed INTEGER NOT NULL,
                    observed_at TEXT NOT NULL
                )"""
            )

    def propose(
        self,
        proposal_id: str,
        target_file: str,
        description: str,
        risk_level: str = "medium",
    ) -> ModificationProposal:
        proposal = ModificationProposal(
            proposal_id=proposal_id, target_file=target_file,
            description=description, risk_level=risk_level,
            test_required=True, ci_required=True,
            canary_required=risk_level in {"medium", "high", "critical"},
            rollback_required=True, created_at=utc_now(),
        )
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO modification_proposals
                (proposal_id, target_file, description, risk_level,
                 test_required, ci_required, canary_required, rollback_required, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (proposal_id, target_file, description, risk_level,
                 1, 1, 1 if proposal.canary_required else 0, 1, utc_now()),
            )
        self._record_phase(proposal_id, "proposed", "started")
        return proposal

    def advance_phase(
        self,
        proposal_id: str,
        to_phase: ModificationPhase,
        *,
        status: str = "completed",
        details: dict[str, Any] | None = None,
    ) -> ModificationPhaseRecord:
        current = self._current_phase(proposal_id)
        expected_next = self._next_expected(current)
        if to_phase != expected_next:
            raise ValueError(
                f"Fase inesperada: se esperaba '{expected_next}', se recibió '{to_phase}'. "
                f"Orden: {' → '.join(PHASE_ORDER)}"
            )
        record = self._record_phase(proposal_id, to_phase, status, details or {})
        return record

    def record_canary_observation(
        self,
        canary_id: str,
        proposal_id: str,
        metric_name: str,
        baseline_value: float,
        canary_value: float,
        tolerance: float = 0.05,
    ) -> CanaryObservation:
        delta = canary_value - baseline_value
        passed = abs(delta) <= abs(baseline_value * tolerance) + tolerance
        obs = CanaryObservation(
            canary_id=canary_id, proposal_id=proposal_id,
            metric_name=metric_name, baseline_value=baseline_value,
            canary_value=canary_value, delta=delta, passed=passed,
            observed_at=utc_now(),
        )
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO canary_observations
                (canary_id, proposal_id, metric_name, baseline_value, canary_value,
                 delta, passed, observed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (canary_id, proposal_id, metric_name, baseline_value,
                 canary_value, delta, 1 if passed else 0, utc_now()),
            )
        return obs

    def canary_verdict(self, proposal_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM canary_observations WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchall()
        if not rows:
            return {"verdict": "no_data", "passed": False}
        total = len(rows)
        passed = sum(1 for r in rows if r["passed"])
        return {
            "verdict": "pass" if passed == total else "fail",
            "passed": passed == total,
            "total_observations": total,
            "passed_observations": passed,
            "failed_observations": total - passed,
        }

    def rollback(self, proposal_id: str, reason: str = "auto_rollback") -> ModificationPhaseRecord:
        record = self._record_phase(proposal_id, "rollback", "applied", {"reason": reason})
        return record

    def status(self, proposal_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            proposal = conn.execute(
                "SELECT * FROM modification_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            phases = conn.execute(
                "SELECT * FROM modification_phases WHERE proposal_id = ? ORDER BY id ASC",
                (proposal_id,),
            ).fetchall()
        if proposal is None:
            return {"status": "not_found"}
        return {
            "proposal": dict(proposal),
            "current_phase": self._current_phase(proposal_id),
            "phases": [dict(p) for p in phases],
        }

    def _current_phase(self, proposal_id: str) -> ModificationPhase:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT phase FROM modification_phases WHERE proposal_id = ? ORDER BY id DESC LIMIT 1",
                (proposal_id,),
            ).fetchone()
        return str(row["phase"]) if row else "proposed"

    def _next_expected(self, current: str) -> ModificationPhase:
        try:
            idx = PHASE_ORDER.index(current)
            if idx + 1 < len(PHASE_ORDER):
                return PHASE_ORDER[idx + 1]
        except ValueError:
            pass
        return "proposed"

    def _record_phase(
        self, proposal_id: str, phase: str, status: str,
        details: dict[str, Any] | None = None,
    ) -> ModificationPhaseRecord:
        now = utc_now()
        record = ModificationPhaseRecord(
            proposal_id=proposal_id, phase=phase, status=status,
            details=details or {}, timestamp=now,
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO modification_phases(proposal_id, phase, status, details_json, recorded_at) VALUES (?, ?, ?, ?, ?)",
                (proposal_id, phase, status,
                 json.dumps(details or {}, ensure_ascii=False), now),
            )
        return record

    def doctor(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) as c FROM modification_proposals").fetchone()["c"]
            by_risk = conn.execute(
                "SELECT risk_level, COUNT(*) as c FROM modification_proposals GROUP BY risk_level"
            ).fetchall()
            canary = conn.execute(
                "SELECT COUNT(DISTINCT proposal_id) as c FROM canary_observations WHERE passed=1"
            ).fetchone()["c"]
        return {
            "total_proposals": total,
            "by_risk_level": {r["risk_level"]: r["c"] for r in by_risk},
            "canary_passed": canary,
            "phase_order": PHASE_ORDER,
        }

"""Validación prolongada: 24h, 72h, 7d, 30d + recuperación de desastres + informe reproducible.

Monitorea estabilidad del sistema a lo largo del tiempo.
Genera informes firmados con SHA-256 para auditoría externa.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from triade.core.contracts import utc_now

ValidationWindow = Literal["24h", "72h", "7d", "30d"]
ValidationStatus = Literal["running", "passed", "failed", "pending"]


@dataclass(frozen=True, slots=True)
class ValidationCheckpoint:
    checkpoint_id: str
    window: ValidationWindow
    status: ValidationStatus
    health_score: float
    total_checks: int
    passed_checks: int
    failed_checks: int
    details: dict[str, Any]
    started_at: str
    completed_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DisasterRecoveryTest:
    test_id: str
    scenario: str
    steps_executed: tuple[str, ...]
    success: bool
    duration_seconds: float
    data_integrity_verified: bool
    executed_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SignedReport:
    report_id: str
    window: ValidationWindow
    checkpoints: tuple[ValidationCheckpoint, ...]
    disaster_recovery: tuple[DisasterRecoveryTest, ...]
    overall_status: ValidationStatus
    overall_score: float
    summary: str
    created_at: str
    checksum: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "window": self.window,
            "checkpoints": [c.to_dict() for c in self.checkpoints],
            "disaster_recovery": [d.to_dict() for d in self.disaster_recovery],
            "overall_status": self.overall_status,
            "overall_score": self.overall_score,
            "summary": self.summary,
            "created_at": self.created_at,
            "checksum": self.checksum,
        }


class ProlongedValidator:
    """Motor de validación prolongada con ventanas de 24h a 30d."""

    WINDOW_SECONDS: dict[ValidationWindow, float] = {
        "24h": 86400,
        "72h": 259200,
        "7d": 604800,
        "30d": 2592000,
    }

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
                """CREATE TABLE IF NOT EXISTS validation_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    window TEXT NOT NULL,
                    status TEXT NOT NULL,
                    health_score REAL NOT NULL,
                    total_checks INTEGER NOT NULL,
                    passed_checks INTEGER NOT NULL,
                    failed_checks INTEGER NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS disaster_recovery_tests (
                    test_id TEXT PRIMARY KEY,
                    scenario TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    duration_seconds REAL NOT NULL,
                    data_integrity_verified INTEGER NOT NULL,
                    executed_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS signed_reports (
                    report_id TEXT PRIMARY KEY,
                    window TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )

    def record_checkpoint(
        self,
        checkpoint_id: str,
        window: ValidationWindow,
        *,
        health_score: float,
        total_checks: int,
        passed_checks: int,
        failed_checks: int,
        details: dict[str, Any] | None = None,
    ) -> ValidationCheckpoint:
        status: ValidationStatus = "passed" if failed_checks == 0 else "failed"
        now = utc_now()
        checkpoint = ValidationCheckpoint(
            checkpoint_id=checkpoint_id, window=window, status=status,
            health_score=health_score, total_checks=total_checks,
            passed_checks=passed_checks, failed_checks=failed_checks,
            details=details or {}, started_at=now, completed_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO validation_checkpoints
                (checkpoint_id, window, status, health_score, total_checks,
                 passed_checks, failed_checks, details_json, started_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (checkpoint_id, window, status, health_score, total_checks,
                 passed_checks, failed_checks,
                 json.dumps(details or {}, ensure_ascii=False), now, now),
            )
        return checkpoint

    def record_disaster_recovery(
        self,
        test_id: str,
        scenario: str,
        steps: list[str],
        success: bool,
        duration_seconds: float,
        data_integrity_verified: bool,
    ) -> DisasterRecoveryTest:
        test = DisasterRecoveryTest(
            test_id=test_id, scenario=scenario,
            steps_executed=tuple(steps), success=success,
            duration_seconds=duration_seconds,
            data_integrity_verified=data_integrity_verified,
            executed_at=utc_now(),
        )
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO disaster_recovery_tests
                (test_id, scenario, steps_json, success, duration_seconds,
                 data_integrity_verified, executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (test_id, scenario, json.dumps(steps, ensure_ascii=False),
                 1 if success else 0, duration_seconds,
                 1 if data_integrity_verified else 0, utc_now()),
            )
        return test

    def generate_signed_report(self, window: ValidationWindow) -> SignedReport:
        with self._connect() as conn:
            cp_rows = conn.execute(
                "SELECT * FROM validation_checkpoints WHERE window = ? ORDER BY started_at",
                (window,),
            ).fetchall()
            dr_rows = conn.execute(
                "SELECT * FROM disaster_recovery_tests ORDER BY executed_at"
            ).fetchall()
        checkpoints = tuple(
            ValidationCheckpoint(
                checkpoint_id=r["checkpoint_id"], window=r["window"],
                status=r["status"], health_score=r["health_score"],
                total_checks=r["total_checks"], passed_checks=r["passed_checks"],
                failed_checks=r["failed_checks"],
                details=json.loads(r["details_json"] or "{}"),
                started_at=r["started_at"], completed_at=r["completed_at"],
            )
            for r in cp_rows
        )
        disaster_recovery = tuple(
            DisasterRecoveryTest(
                test_id=r["test_id"], scenario=r["scenario"],
                steps_executed=tuple(json.loads(r["steps_json"])),
                success=bool(r["success"]),
                duration_seconds=r["duration_seconds"],
                data_integrity_verified=bool(r["data_integrity_verified"]),
                executed_at=r["executed_at"],
            )
            for r in dr_rows
        )
        total_cp = len(checkpoints)
        passed_cp = sum(1 for c in checkpoints if c.status == "passed")
        total_dr = len(disaster_recovery)
        passed_dr = sum(1 for d in disaster_recovery if d.success)
        overall_score = 0.0
        if total_cp + total_dr > 0:
            overall_score = round((passed_cp + passed_dr) / (total_cp + total_dr), 3)
        overall_status: ValidationStatus = "passed" if overall_score >= 0.9 else "failed"
        summary = (
            f"Validación {window}: {passed_cp}/{total_cp} checkpoints pasaron, "
            f"{passed_dr}/{total_dr} tests de recuperación pasaron. "
            f"Score={overall_score}. Estado={overall_status}."
        )
        report = SignedReport(
            report_id=f"report-{window}-{int(__import__('time').time())}",
            window=window, checkpoints=checkpoints,
            disaster_recovery=disaster_recovery,
            overall_status=overall_status, overall_score=overall_score,
            summary=summary, created_at=utc_now(), checksum="",
        )
        checksum = self._compute_checksum(report)
        report = SignedReport(
            report_id=report.report_id, window=window,
            checkpoints=checkpoints, disaster_recovery=disaster_recovery,
            overall_status=overall_status, overall_score=overall_score,
            summary=summary, created_at=report.created_at, checksum=checksum,
        )
        self._persist_report(report)
        return report

    def verify_report(self, report_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM signed_reports WHERE report_id = ?", (report_id,)
            ).fetchone()
        if row is None:
            return {"valid": False, "error": "Reporte no encontrado"}
        report_data = json.loads(row["report_json"])
        stored_checksum = row["checksum"]
        recomputed = hashlib.sha256(
            json.dumps(report_data, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]
        return {
            "valid": stored_checksum == recomputed,
            "stored_checksum": stored_checksum,
            "recomputed_checksum": recomputed,
            "window": row["window"],
            "created_at": row["created_at"],
        }

    def get_checkpoints(self, window: ValidationWindow) -> list[ValidationCheckpoint]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM validation_checkpoints WHERE window = ? ORDER BY started_at",
                (window,),
            ).fetchall()
        return [
            ValidationCheckpoint(
                checkpoint_id=r["checkpoint_id"], window=r["window"],
                status=r["status"], health_score=r["health_score"],
                total_checks=r["total_checks"], passed_checks=r["passed_checks"],
                failed_checks=r["failed_checks"],
                details=json.loads(r["details_json"] or "{}"),
                started_at=r["started_at"], completed_at=r["completed_at"],
            )
            for r in rows
        ]

    @staticmethod
    def _compute_checksum(report: SignedReport) -> str:
        data = report.to_dict()
        data.pop("checksum", None)
        return hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]

    def _persist_report(self, report: SignedReport) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO signed_reports(report_id, window, report_json, checksum, created_at) VALUES (?, ?, ?, ?, ?)",
                (report.report_id, report.window,
                 json.dumps(report.to_dict(), ensure_ascii=False),
                 report.checksum, report.created_at),
            )

    def doctor(self) -> dict[str, Any]:
        with self._connect() as conn:
            checkpoints = conn.execute("SELECT COUNT(*) as c FROM validation_checkpoints").fetchone()["c"]
            dr_tests = conn.execute("SELECT COUNT(*) as c FROM disaster_recovery_tests").fetchone()["c"]
            reports = conn.execute("SELECT COUNT(*) as c FROM signed_reports").fetchone()["c"]
        return {
            "checkpoints_recorded": checkpoints,
            "disaster_recovery_tests": dr_tests,
            "signed_reports": reports,
            "windows": list(self.WINDOW_SECONDS.keys()),
        }

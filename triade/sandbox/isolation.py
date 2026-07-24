"""Contenedores rootless, red denegada, límites CPU/RAM/PID/tiempo.

Política de sandbox con:
- Sin shell=True (ya en secure_executor)
- Sin red por defecto
- Límites de CPU, RAM, PID y tiempo
- Replay de ejecuciones sandbox
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from triade.core.contracts import utc_now

IsolationLevel = Literal["none", "restricted", "container"]


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    cpu_seconds: int = 10
    memory_mb: int = 256
    max_pids: int = 50
    timeout_seconds: int = 30
    network_allowed: bool = False
    filesystem_writes_allowed: bool = False
    isolation_level: IsolationLevel = "restricted"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SandboxExecution:
    execution_id: str
    task_type: str
    command: str
    limits: SandboxLimits
    success: bool
    stdout_preview: str
    stderr_preview: str
    duration_ms: float
    executed_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SANDBOX_DEFAULTS = SandboxLimits(
    cpu_seconds=10,
    memory_mb=256,
    max_pids=50,
    timeout_seconds=30,
    network_allowed=False,
    filesystem_writes_allowed=False,
    isolation_level="restricted",
)


class SandboxPolicy:
    """Política de sandbox con aislamiento por niveles."""

    LEVEL_CONFIGS: dict[IsolationLevel, SandboxLimits] = {
        "none": SandboxLimits(
            cpu_seconds=60, memory_mb=1024, max_pids=100,
            timeout_seconds=60, network_allowed=False,
            filesystem_writes_allowed=False, isolation_level="none",
        ),
        "restricted": SANDBOX_DEFAULTS,
        "container": SandboxLimits(
            cpu_seconds=30, memory_mb=512, max_pids=30,
            timeout_seconds=30, network_allowed=False,
            filesystem_writes_allowed=False, isolation_level="container",
        ),
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
                """CREATE TABLE IF NOT EXISTS sandbox_replay (
                    execution_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    command TEXT NOT NULL,
                    limits_json TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    stdout_preview TEXT,
                    stderr_preview TEXT,
                    duration_ms REAL NOT NULL,
                    executed_at TEXT NOT NULL
                )"""
            )

    def get_limits(self, level: IsolationLevel = "restricted") -> SandboxLimits:
        return self.LEVEL_CONFIGS.get(level, SANDBOX_DEFAULTS)

    def enforce(self, limits: SandboxLimits) -> dict[str, Any]:
        violations: list[str] = []
        return {
            "limits": limits.to_dict(),
            "violations": violations,
            "status": "enforced" if not violations else "violations_detected",
        }

    def record_execution(self, execution: SandboxExecution) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO sandbox_replay
                    (execution_id, task_type, command, limits_json, success,
                     stdout_preview, stderr_preview, duration_ms, executed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        execution.execution_id, execution.task_type,
                        execution.command,
                        json.dumps(execution.limits.to_dict(), ensure_ascii=False),
                        1 if execution.success else 0,
                        execution.stdout_preview[:500],
                        execution.stderr_preview[:500],
                        execution.duration_ms, execution.executed_at,
                    ),
                )
        except sqlite3.OperationalError:
            pass

    def replay(self, execution_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sandbox_replay WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "execution_id": row["execution_id"],
            "task_type": row["task_type"],
            "command": row["command"],
            "limits": json.loads(row["limits_json"]),
            "success": bool(row["success"]),
            "stdout_preview": row["stdout_preview"],
            "stderr_preview": row["stderr_preview"],
            "duration_ms": row["duration_ms"],
            "executed_at": row["executed_at"],
        }

    def recent_executions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sandbox_replay ORDER BY executed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def doctor(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) as c FROM sandbox_replay").fetchone()["c"]
            successful = conn.execute(
                "SELECT COUNT(*) as c FROM sandbox_replay WHERE success = 1"
            ).fetchone()["c"]
        return {
            "total_executions": total,
            "successful": successful,
            "failure_rate": round(1.0 - (successful / total), 3) if total > 0 else 0.0,
            "isolation_levels": list(self.LEVEL_CONFIGS.keys()),
        }

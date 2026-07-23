"""Sandbox autónomo con rollback verificable y snapshots SHA-256.

Tríade Ω — Autonomous Sandbox

Reglas:
- Snapshot de archivos antes de ejecutar código.
- Detectar cambios post-ejecución comparando hashes.
- Rollback restaura el contenido original desde el snapshot.
- Todo se registra en SQLite para auditoría completa.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now


@dataclass(slots=True)
class SandboxExecution:
    execution_id: str
    task_type: str
    code: str
    working_dir: str
    snapshot_before: dict[str, str]
    result: dict[str, Any] = field(default_factory=dict)
    success: bool = False
    rollback_available: bool = False
    created_at: str = ""


class AutonomousSandbox:
    """Ejecuta código en sandbox aislado con snapshot/rollback de archivos."""

    def __init__(self, db_path: str | Path, runs_dir: str | Path) -> None:
        self.db_path = Path(db_path)
        self.runs_dir = Path(runs_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS sandbox_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    execution_id TEXT NOT NULL UNIQUE,
                    task_type TEXT NOT NULL,
                    code_preview TEXT DEFAULT '',
                    working_dir TEXT DEFAULT '',
                    snapshot_json TEXT DEFAULT '{}',
                    changes_json TEXT DEFAULT '{}',
                    success INTEGER DEFAULT 0,
                    rollback_performed INTEGER DEFAULT 0,
                    rollback_verified INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sandbox_executions_task_type "
                "ON sandbox_executions(task_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sandbox_executions_created_at "
                "ON sandbox_executions(created_at)"
            )

    def create_snapshot(self, files_to_watch: list[str | Path]) -> dict[str, str]:
        """Captura SHA-256 de cada archivo existente."""
        snapshot: dict[str, str] = {}
        for filepath in files_to_watch:
            p = Path(filepath)
            if p.is_file():
                snapshot[str(p.resolve())] = self._hash_file(p)
            else:
                snapshot[str(p.resolve())] = ""
        return snapshot

    def _hash_file(self, path: Path) -> str:
        sha = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)
        return sha.hexdigest()

    def execute_code(
        self,
        task_type: str,
        code: str,
        working_dir: str | Path,
        timeout: int = 30,
    ) -> SandboxExecution:
        """Ejecuta código, captura snapshot antes y detecta cambios después."""
        execution_id = f"sandbox_{int(__import__('time').time() * 1000)}_{os.getpid()}"
        workdir = Path(working_dir)
        workdir.mkdir(parents=True, exist_ok=True)

        # Backup de archivos que existan antes de ejecutar
        backup_dir = self.runs_dir / execution_id / "_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backed_up: dict[str, str] = {}
        existing = [f for f in workdir.rglob("*") if f.is_file()]
        for f in existing:
            rel = f.relative_to(workdir)
            backup_path = backup_dir / rel
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, backup_path)
            backed_up[str(f.resolve())] = str(backup_path)

        # Snapshot de hashes post-backup (pre-ejecución)
        snapshot = self.create_snapshot(list(workdir.rglob("*")))
        # Filtrar solo archivos reales (no vacíos)
        snapshot = {k: v for k, v in snapshot.items() if v}

        # Ejecutar código
        result: dict[str, Any] = {}
        success = False
        code_path = workdir / "_sandbox_exec.py"
        try:
            code_path.write_text(code, encoding="utf-8")
            proc = subprocess.run(
                ["python", str(code_path)],
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            result = {
                "stdout": proc.stdout[-4000:] if proc.stdout else "",
                "stderr": proc.stderr[-4000:] if proc.stderr else "",
                "returncode": proc.returncode,
            }
            success = proc.returncode == 0
        except subprocess.TimeoutExpired:
            result = {"stdout": "", "stderr": "Timeout expired", "returncode": -1}
            success = False
        except Exception as exc:  # noqa: BLE001
            result = {"stdout": "", "stderr": f"{type(exc).__name__}: {exc}", "returncode": -1}
            success = False
        finally:
            if code_path.exists():
                code_path.unlink(missing_ok=True)

        # Detectar cambios post-ejecución
        post_snapshot = self.create_snapshot(list(workdir.rglob("*")))
        changes: dict[str, dict[str, str]] = {}
        for fp in set(list(snapshot.keys()) + list(post_snapshot.keys())):
            pre = snapshot.get(fp, "")
            post = post_snapshot.get(fp, "")
            if pre != post:
                changes[fp] = {"before": pre, "after": post}

        execution = SandboxExecution(
            execution_id=execution_id,
            task_type=task_type,
            code=code[:2000],
            working_dir=str(workdir),
            snapshot_before=snapshot,
            result=result,
            success=success,
            rollback_available=bool(changes),
            created_at=utc_now(),
        )

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO sandbox_executions
                (execution_id, task_type, code_preview, working_dir,
                 snapshot_json, changes_json, success, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    execution_id,
                    task_type,
                    code[:2000],
                    str(workdir),
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    json.dumps(changes, ensure_ascii=False, sort_keys=True),
                    1 if success else 0,
                    execution.created_at,
                ),
            )

        return execution

    def rollback(self, execution_id: str) -> bool:
        """Restaura archivos al estado previo usando backups tomados antes de ejecutar."""
        row = self._get_row(execution_id)
        if row is None:
            return False

        backup_dir = self.runs_dir / execution_id / "_backups"
        if not backup_dir.exists():
            return False

        snapshot: dict[str, str] = json.loads(row["snapshot_json"] or "{}")
        workdir = Path(row["working_dir"])

        restored = 0
        for backup_file in backup_dir.rglob("*"):
            if not backup_file.is_file():
                continue
            rel = backup_file.relative_to(backup_dir)
            target = workdir / rel
            if target.exists() or target.parent.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_file, target)
                restored += 1

        # Eliminar archivos que no existían antes
        for fp in workdir.rglob("*"):
            if fp.is_file() and str(fp.resolve()) not in snapshot:
                fp.unlink(missing_ok=True)

        with self._connect() as conn:
            conn.execute(
                "UPDATE sandbox_executions SET rollback_performed = 1 WHERE execution_id = ?",
                (execution_id,),
            )

        return restored > 0 or len(snapshot) > 0

    def verify_rollback(self, execution_id: str) -> bool:
        """Verifica que los archivos actuales coinciden con el snapshot."""
        row = self._get_row(execution_id)
        if row is None:
            return False

        snapshot: dict[str, str] = json.loads(row["snapshot_json"] or "{}")
        workdir = Path(row["working_dir"])

        current = self.create_snapshot(list(workdir.rglob("*")))
        # Comparar solo archivos que estaban en el snapshot original
        all_match = True
        for fp, expected_hash in snapshot.items():
            actual_hash = current.get(fp, "")
            if actual_hash != expected_hash:
                all_match = False
                break

        if all_match:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE sandbox_executions SET rollback_verified = 1 WHERE execution_id = ?",
                    (execution_id,),
                )

        return all_match

    def get_execution_history(self, limit: int = 50) -> list[SandboxExecution]:
        """Devuelve las ejecuciones más recientes."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sandbox_executions ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_execution(r) for r in rows]

    def get_rollback_history(self) -> list[dict[str, Any]]:
        """Muestra todas las ejecuciones donde se realizó rollback."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT execution_id, task_type, working_dir, created_at,
                   rollback_verified
                   FROM sandbox_executions
                   WHERE rollback_performed = 1
                   ORDER BY id DESC"""
            ).fetchall()
        return [
            {
                "execution_id": str(r["execution_id"]),
                "task_type": str(r["task_type"]),
                "working_dir": str(r["working_dir"]),
                "rollback_verified": bool(r["rollback_verified"]),
                "created_at": str(r["created_at"]),
            }
            for r in rows
        ]

    def get_sandbox_stats(self) -> dict[str, Any]:
        """Estadísticas de ejecuciones y rollbacks."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM sandbox_executions").fetchone()["c"]
            successes = conn.execute(
                "SELECT COUNT(*) AS c FROM sandbox_executions WHERE success = 1"
            ).fetchone()["c"]
            rollbacks = conn.execute(
                "SELECT COUNT(*) AS c FROM sandbox_executions WHERE rollback_performed = 1"
            ).fetchone()["c"]
            verified = conn.execute(
                "SELECT COUNT(*) AS c FROM sandbox_executions WHERE rollback_verified = 1"
            ).fetchone()["c"]
        total_int = int(total)
        return {
            "total_executions": total_int,
            "successful": int(successes),
            "failed": total_int - int(successes),
            "success_rate": round(int(successes) / total_int, 4) if total_int else 0.0,
            "rollbacks_performed": int(rollbacks),
            "rollbacks_verified": int(verified),
            "rollback_rate": round(int(rollbacks) / total_int, 4) if total_int else 0.0,
            "rollback_verification_rate": (
                round(int(verified) / int(rollbacks), 4) if rollbacks else 0.0
            ),
        }

    def _get_row(self, execution_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM sandbox_executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()

    def _row_to_execution(self, row: sqlite3.Row) -> SandboxExecution:
        return SandboxExecution(
            execution_id=str(row["execution_id"]),
            task_type=str(row["task_type"]),
            code=str(row["code_preview"]),
            working_dir=str(row["working_dir"]),
            snapshot_before=json.loads(row["snapshot_json"] or "{}"),
            result=json.loads(row["changes_json"] or "{}"),
            success=bool(row["success"]),
            rollback_available=bool(row["rollback_performed"]),
            created_at=str(row["created_at"]),
        )

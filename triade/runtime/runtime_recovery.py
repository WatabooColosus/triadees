"""Recuperación conservadora y auditable, sin shell ni systemctl embebido."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from triade.runtime.task_leases import AutonomousTaskStore


class RuntimeRecovery:
    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        snapshot_dir: str | Path = "artifacts/recovery",
    ) -> None:
        self.db_path = Path(db_path)
        self.snapshot_dir = Path(snapshot_dir)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.tasks = AutonomousTaskStore(self.db_path)

    def recover(
        self,
        cause: str,
        *,
        stop_workers: Callable[[], Any] | None = None,
        start_workers: Callable[[], Any] | None = None,
        verify_heartbeat: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        recovery_id = f"recovery-{uuid4().hex[:16]}"
        created = datetime.now(UTC).isoformat()
        actions: list[dict[str, Any]] = []
        snapshot = self._snapshot(recovery_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO runtime_recovery_events
                (recovery_id,cause,state,snapshot_ref,actions_json,created_at) VALUES(?,?,'recovering',?,? ,?)""",
                (recovery_id, cause, snapshot, "[]", created),
            )
        try:
            if stop_workers:
                actions.append({"action": "stop_workers", "result": stop_workers()})
            recovered = self.tasks.recover_expired()
            actions.append({"action": "recover_expired_leases", "task_ids": recovered})
            with sqlite3.connect(self.db_path, timeout=5) as conn:
                integrity = str(conn.execute("PRAGMA quick_check").fetchone()[0])
            actions.append({"action": "sqlite_quick_check", "result": integrity})
            if integrity != "ok":
                raise RuntimeError("sqlite_quick_check_failed")
            if start_workers:
                actions.append({"action": "start_workers", "result": start_workers()})
            heartbeat_ok = verify_heartbeat() if verify_heartbeat else True
            actions.append({"action": "verify_heartbeat", "result": bool(heartbeat_ok)})
            if not heartbeat_ok:
                raise RuntimeError("new_heartbeat_not_observed")
            state, error = "runtime_recovered", None
        except (
            OSError,
            ImportError,
            sqlite3.Error,
            RuntimeError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ) as exc:
            state, error = "critical", f"{type(exc).__name__}: {exc}"
        finished = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE runtime_recovery_events SET state=?,actions_json=?,error=?,finished_at=? WHERE recovery_id=?",
                (
                    state,
                    json.dumps(actions, ensure_ascii=False, default=str),
                    error,
                    finished,
                    recovery_id,
                ),
            )
        return {
            "recovery_id": recovery_id,
            "state": state,
            "snapshot_ref": snapshot,
            "actions": actions,
            "error": error,
            "rollback": {"database_snapshot": snapshot},
        }

    def _snapshot(self, recovery_id: str) -> str:
        output = self.snapshot_dir / f"{recovery_id}.db"
        with sqlite3.connect(self.db_path) as source, sqlite3.connect(output) as target:
            source.backup(target)
        output.chmod(0o600)
        self.enforce_snapshot_retention(max_archives_per_run=2)
        return str(output)

    def enforce_snapshot_retention(
        self, *, keep_recent: int = 10, max_archives_per_run: int | None = 25
    ) -> dict[str, Any]:
        snapshots = sorted(
            self.snapshot_dir.glob("recovery-*.db"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        candidates = snapshots[max(1, keep_recent) :]
        if max_archives_per_run is not None:
            candidates = candidates[: max(0, max_archives_per_run)]
        quarantine = self.snapshot_dir / "quarantine"
        quarantine.mkdir(parents=True, exist_ok=True)
        archived: list[dict[str, Any]] = []
        bytes_reclaimed = 0
        for snapshot in candidates:
            raw_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
            archive = quarantine / f"{snapshot.name}.gz"
            temporary = archive.with_suffix(".gz.tmp")
            with (
                snapshot.open("rb") as source,
                gzip.open(temporary, "wb", compresslevel=6) as target,
            ):
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
            with gzip.open(temporary, "rb") as restored:
                restored_hash = hashlib.sha256(restored.read()).hexdigest()
            if restored_hash != raw_hash:
                temporary.unlink(missing_ok=True)
                raise RuntimeError("recovery_snapshot_archive_verification_failed")
            os.replace(temporary, archive)
            archive.chmod(0o600)
            manifest = {
                "source": snapshot.name,
                "archive": archive.name,
                "source_sha256": raw_hash,
                "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "source_bytes": snapshot.stat().st_size,
                "archive_bytes": archive.stat().st_size,
                "recoverable": True,
                "created_at": datetime.now(UTC).isoformat(),
            }
            manifest_path = archive.with_suffix(".gz.json")
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            manifest_path.chmod(0o600)
            bytes_reclaimed += snapshot.stat().st_size - archive.stat().st_size
            snapshot.unlink()
            archived.append(manifest)
        return {
            "status": "completed",
            "kept_recent": min(len(snapshots), max(1, keep_recent)),
            "archived": archived,
            "bytes_reclaimed": bytes_reclaimed,
            "remaining_plain_snapshots": len(
                list(self.snapshot_dir.glob("recovery-*.db"))
            ),
            "quarantine_dir": str(quarantine),
        }

    @staticmethod
    def restore_archived_snapshot(
        archive: str | Path, destination: str | Path
    ) -> dict[str, Any]:
        archive_path = Path(archive)
        manifest_path = archive_path.with_suffix(".gz.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if hashlib.sha256(archive_path.read_bytes()).hexdigest() != manifest.get(
            "archive_sha256"
        ):
            raise ValueError("recovery_archive_hash_mismatch")
        with gzip.open(archive_path, "rb") as source:
            raw = source.read()
        if hashlib.sha256(raw).hexdigest() != manifest.get("source_sha256"):
            raise ValueError("recovery_snapshot_hash_mismatch")
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(raw)
        with sqlite3.connect(temporary) as conn:
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            temporary.unlink(missing_ok=True)
            raise ValueError("recovery_snapshot_integrity_failed")
        os.replace(temporary, target)
        return {
            "status": "restored",
            "destination": str(target),
            "integrity_check": integrity,
            "source_sha256": manifest["source_sha256"],
        }

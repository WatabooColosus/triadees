"""Backup SQLite cifrado y restauración comprobada (opt-in por clave)."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any


class EncryptedBackup:
    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        backup_dir: str | Path = "artifacts/backups",
        minimum_interval_seconds: int = 300,
        require_identity_manifest: bool = False,
    ) -> None:
        self.db_path, self.backup_dir = Path(db_path), Path(backup_dir)
        self.minimum_interval_seconds = max(0, minimum_interval_seconds)
        self.require_identity_manifest = require_identity_manifest
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _fernet():
        from cryptography.fernet import Fernet

        key = os.getenv("TRIADE_BACKUP_KEY", "").encode()
        if not key:
            raise RuntimeError(
                "TRIADE_BACKUP_KEY requerida; no se crean backups sin cifrado"
            )
        return Fernet(key)

    def create(self, *, force: bool = False) -> dict[str, Any]:
        recent = sorted(
            self.backup_dir.glob("triade-*.db.gz.fernet"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if (
            recent
            and not force
            and time.time() - recent[0].stat().st_mtime < self.minimum_interval_seconds
        ):
            return {
                "status": "blocked",
                "reason": "backup_cooldown_active",
                "latest": str(recent[0]),
            }
        with tempfile.TemporaryDirectory(prefix="triade-backup-") as directory:
            snapshot = Path(directory) / "snapshot.db"
            with (
                sqlite3.connect(self.db_path) as source,
                sqlite3.connect(snapshot) as target,
            ):
                source.backup(target)
            snapshot_bytes = snapshot.read_bytes()
            plaintext = gzip.compress(snapshot_bytes)
        encrypted = self._fernet().encrypt(plaintext)
        digest = hashlib.sha256(encrypted).hexdigest()
        output = (
            self.backup_dir / f"triade-{int(time.time())}-{digest[:12]}.db.gz.fernet"
        )
        output.write_bytes(encrypted)
        manifest = {
            "file": output.name,
            "sha256": digest,
            "source": str(self.db_path),
            "encrypted": True,
            "created_at": time.time(),
            "source_db_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
            "source_size_bytes": len(snapshot_bytes),
        }
        output.with_suffix(output.suffix + ".json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        return {"status": "completed", **manifest}

    def verify(self, backup: str | Path) -> dict[str, Any]:
        backup_path = Path(backup)
        encrypted = backup_path.read_bytes()
        manifest_path = backup_path.with_suffix(backup_path.suffix + ".json")
        if not manifest_path.is_file():
            raise ValueError("backup_manifest_missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        encrypted_hash = hashlib.sha256(encrypted).hexdigest()
        if encrypted_hash != manifest.get("sha256"):
            raise ValueError("encrypted_backup_hash_mismatch")
        raw = gzip.decompress(self._fernet().decrypt(encrypted))
        if hashlib.sha256(raw).hexdigest() != manifest.get("source_db_sha256"):
            raise ValueError("restored_database_hash_mismatch")
        with tempfile.TemporaryDirectory(prefix="triade-restore-test-") as directory:
            test_db = Path(directory) / "restore.db"
            test_db.write_bytes(raw)
            semantic = self._semantic_verification(test_db)
            if (
                self.require_identity_manifest
                and not semantic["identity_manifest_hash"]
            ):
                raise ValueError("identity_manifest_missing")
        return {
            "status": "ok" if semantic["integrity_check"] == "ok" else "error",
            "sha256": encrypted_hash,
            **semantic,
        }

    @staticmethod
    def _semantic_verification(db_path: Path) -> dict[str, Any]:
        with sqlite3.connect(db_path) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            memory_count = (
                conn.execute("SELECT COUNT(*) FROM semantic_memory").fetchone()[0]
                if "semantic_memory" in tables
                else 0
            )
            task_states = (
                dict(
                    conn.execute(
                        "SELECT status,COUNT(*) FROM autonomous_tasks GROUP BY status"
                    )
                )
                if "autonomous_tasks" in tables
                else {}
            )
            identity_anchor = (
                conn.execute(
                    "SELECT manifest_hash FROM identity_manifest_anchor WHERE singleton=1"
                ).fetchone()
                if "identity_manifest_anchor" in tables
                else None
            )
            artifacts_checked = 0
            artifact_failures: list[str] = []
            if "autonomous_tasks" in tables:
                for (result_ref,) in conn.execute(
                    "SELECT result_ref FROM autonomous_tasks WHERE result_ref IS NOT NULL"
                ):
                    path = Path(str(result_ref))
                    if path.is_file():
                        artifacts_checked += 1
                    else:
                        artifact_failures.append(str(path))
        return {
            "integrity_check": integrity,
            "identity_manifest_hash": identity_anchor[0] if identity_anchor else None,
            "semantic_memory_count": memory_count,
            "task_states": task_states,
            "artifact_refs_checked": artifacts_checked,
            "artifact_ref_failures": artifact_failures,
        }

    def enforce_retention(
        self, *, keep_daily: int = 7, keep_weekly: int = 4
    ) -> dict[str, Any]:
        """Conserva los N diarios recientes y una muestra semanal; nunca borra el último."""
        files = sorted(
            self.backup_dir.glob("triade-*.db.gz.fernet"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        keep: set[Path] = set(files[: max(1, keep_daily)])
        weeks: set[str] = set()
        for path in files[max(1, keep_daily) :]:
            week = time.strftime("%Y-%W", time.gmtime(path.stat().st_mtime))
            if len(weeks) < max(0, keep_weekly) and week not in weeks:
                weeks.add(week)
                keep.add(path)
        removed = []
        for path in files:
            if path in keep:
                continue
            manifest = path.with_suffix(path.suffix + ".json")
            quarantine = self.backup_dir / "quarantine"
            quarantine.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), quarantine / path.name)
            if manifest.exists():
                shutil.move(str(manifest), quarantine / manifest.name)
            removed.append(path.name)
        return {
            "status": "completed",
            "kept": len(keep),
            "removed": removed,
            "policy": {"daily": keep_daily, "weekly": keep_weekly},
            "quarantine_dir": str(self.backup_dir / "quarantine"),
            "bytes_kept": sum(path.stat().st_size for path in keep if path.exists()),
        }

    def restore_to_sandbox(
        self, backup: str | Path, destination: str | Path
    ) -> dict[str, Any]:
        verification = self.verify(backup)
        encrypted = Path(backup).read_bytes()
        raw = gzip.decompress(self._fernet().decrypt(encrypted))
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="triade-sandbox-restore-") as directory:
            source_path = Path(directory) / "source.db"
            source_path.write_bytes(raw)
            with (
                sqlite3.connect(source_path) as source,
                sqlite3.connect(target) as output,
            ):
                source.backup(output)
        restored = self._semantic_verification(target)
        return {
            "status": "restored_sandbox"
            if restored["integrity_check"] == "ok"
            else "error",
            "destination": str(target),
            "production_overwritten": target.resolve() == self.db_path.resolve(),
            "verification": verification,
            "restored": restored,
        }

    def restore(self, backup: str | Path, *, human_approved: bool) -> dict[str, Any]:
        if not human_approved:
            return {"status": "blocked", "reason": "human_approval_required"}
        verification = self.verify(backup)
        if verification["status"] != "ok":
            return verification
        pre_restore = self.create(force=True)
        raw = gzip.decompress(self._fernet().decrypt(Path(backup).read_bytes()))
        with tempfile.TemporaryDirectory(
            prefix="triade-production-restore-"
        ) as directory:
            source_path = Path(directory) / "source.db"
            source_path.write_bytes(raw)
            with (
                sqlite3.connect(source_path) as source,
                sqlite3.connect(self.db_path) as target,
            ):
                source.backup(target)
        return {
            "status": "restored",
            "verification": verification,
            "pre_restore_backup": pre_restore,
        }

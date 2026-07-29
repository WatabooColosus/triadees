"""Backup SQLite cifrado y restauración comprobada (opt-in por clave)."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any


class EncryptedBackup:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db", backup_dir: str | Path = "artifacts/backups") -> None:
        self.db_path, self.backup_dir = Path(db_path), Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _fernet():
        from cryptography.fernet import Fernet
        key = os.getenv("TRIADE_BACKUP_KEY", "").encode()
        if not key:
            raise RuntimeError("TRIADE_BACKUP_KEY requerida; no se crean backups sin cifrado")
        return Fernet(key)

    def create(self) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="triade-backup-") as directory:
            snapshot = Path(directory) / "snapshot.db"
            with sqlite3.connect(self.db_path) as source, sqlite3.connect(snapshot) as target:
                source.backup(target)
            plaintext = gzip.compress(snapshot.read_bytes())
        encrypted = self._fernet().encrypt(plaintext)
        digest = hashlib.sha256(encrypted).hexdigest()
        output = self.backup_dir / f"triade-{int(time.time())}-{digest[:12]}.db.gz.fernet"
        output.write_bytes(encrypted)
        manifest = {"file": output.name, "sha256": digest, "source": str(self.db_path),
                    "encrypted": True, "created_at": time.time()}
        output.with_suffix(output.suffix + ".json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {"status": "completed", **manifest}

    def verify(self, backup: str | Path) -> dict[str, Any]:
        raw = gzip.decompress(self._fernet().decrypt(Path(backup).read_bytes()))
        with tempfile.TemporaryDirectory(prefix="triade-restore-test-") as directory:
            test_db = Path(directory) / "restore.db"; test_db.write_bytes(raw)
            with sqlite3.connect(test_db) as conn:
                check = conn.execute("PRAGMA integrity_check").fetchone()[0]
        return {"status": "ok" if check == "ok" else "error", "integrity_check": check,
                "sha256": hashlib.sha256(Path(backup).read_bytes()).hexdigest()}

    def enforce_retention(self, *, keep_daily: int = 7, keep_weekly: int = 4) -> dict[str, Any]:
        """Conserva los N diarios recientes y una muestra semanal; nunca borra el último."""
        files = sorted(self.backup_dir.glob("triade-*.db.gz.fernet"), key=lambda p: p.stat().st_mtime, reverse=True)
        keep: set[Path] = set(files[: max(1, keep_daily)])
        weeks: set[str] = set()
        for path in files[max(1, keep_daily):]:
            week = time.strftime("%Y-%W", time.gmtime(path.stat().st_mtime))
            if len(weeks) < max(0, keep_weekly) and week not in weeks:
                weeks.add(week); keep.add(path)
        removed = []
        for path in files:
            if path in keep:
                continue
            manifest = path.with_suffix(path.suffix + ".json")
            path.unlink(missing_ok=True); manifest.unlink(missing_ok=True); removed.append(path.name)
        return {"status": "completed", "kept": len(keep), "removed": removed,
                "policy": {"daily": keep_daily, "weekly": keep_weekly}}

    def restore(self, backup: str | Path, *, human_approved: bool) -> dict[str, Any]:
        if not human_approved:
            return {"status": "blocked", "reason": "human_approval_required"}
        verification = self.verify(backup)
        if verification["status"] != "ok":
            return verification
        pre_restore = self.create()
        raw = gzip.decompress(self._fernet().decrypt(Path(backup).read_bytes()))
        self.db_path.write_bytes(raw)
        return {"status": "restored", "verification": verification, "pre_restore_backup": pre_restore}

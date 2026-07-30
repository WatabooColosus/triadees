#!/usr/bin/env python3
"""Backup cifrado, verificación y retención para timer externo."""

from pathlib import Path

from triade.memory.encrypted_backup import EncryptedBackup

if __name__ == "__main__":
    backup = EncryptedBackup()
    created = backup.create()
    verified = backup.verify(Path("artifacts/backups") / created["file"])
    if verified.get("status") != "ok":
        raise SystemExit("backup verification failed")
    backup.enforce_retention()
    drill = backup.run_restore_drill()
    if drill.get("status") not in {"completed", "blocked"}:
        raise SystemExit("restore drill failed")

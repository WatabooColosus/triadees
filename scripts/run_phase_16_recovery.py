#!/usr/bin/env python3
"""Crea backup cifrado de una snapshot runtime y verifica restore sandbox."""

import json
import os
import sqlite3
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from triade.memory.encrypted_backup import EncryptedBackup


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        snapshot = root / "runtime.db"
        with (
            sqlite3.connect("triade/memory/triade.db") as source,
            sqlite3.connect(snapshot) as target,
        ):
            source.backup(target)
        key = Fernet.generate_key().decode()
        os.environ["TRIADE_BACKUP_KEY"] = key
        backup = EncryptedBackup(
            snapshot,
            root / "backups",
            minimum_interval_seconds=300,
            require_identity_manifest=True,
        )
        created = backup.create()
        path = root / "backups" / created["file"]
        verified = backup.verify(path)
        restored = backup.restore_to_sandbox(path, root / "sandbox" / "triade.db")
        cooldown = backup.create()
        original_key = os.environ["TRIADE_BACKUP_KEY"]
        os.environ["TRIADE_BACKUP_KEY"] = Fernet.generate_key().decode()
        wrong_key_failed = False
        try:
            backup.verify(path)
        except InvalidToken:
            wrong_key_failed = True
        finally:
            os.environ["TRIADE_BACKUP_KEY"] = original_key
        report = {
            "phase": 16,
            "created": {
                key: value for key, value in created.items() if key != "source"
            },
            "verified": verified,
            "restored": restored,
            "wrong_key_failed": wrong_key_failed,
            "cooldown_blocked": cooldown.get("status") == "blocked",
            "production_restore_attempted": False,
        }
        report["passed"] = all(
            (
                verified["status"] == "ok",
                restored["status"] == "restored_sandbox",
                not restored["production_overwritten"],
                wrong_key_failed,
                report["cooldown_blocked"],
            )
        )
    output = Path("artifacts/triade_verify/phase_16/recovery.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Evidencia runtime reproducible para la Fase 3 de TRIADE-VERIFY-v1."""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from triade.core.identity_continuity import IdentityContinuity


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/triade_verify/phase_03/identity_continuity.json",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="triade-phase03-") as raw_tmp:
        root = Path(raw_tmp)
        db_path = root / "triade.db"
        continuity = IdentityContinuity(db_path)
        first = continuity.verify(run_id="phase03-start-1")
        second = IdentityContinuity(db_path).verify(run_id="phase03-start-2")
        migration = continuity.migrate_anchor(
            approved_by="human:phase03-validation",
            reason="reproducible identity recovery exercise",
            backup_dir=root / "backups",
        )
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE identity_core SET value = ? WHERE key = 'entity_name'",
                ("runtime-tamper-probe",),
            )
        tampered = continuity.verify(run_id="phase03-tampered")
        restored = continuity.restore_to_sandbox(
            migration["backup_ref"], root / "restored" / "triade.db"
        )

        checks = {
            "initial_integrity_verified": first["integrity"] == "verified",
            "restart_continuity_verified": second["continuity_from_previous_run"]
            is True,
            "tamper_detected": tampered["tamper_detected"] is True,
            "tamper_enters_degraded_safe": tampered["integrity"] == "degraded_safe",
            "restore_sqlite_integrity": restored["sqlite_integrity"] == "ok",
            "restore_identity_verified": restored["status"] == "verified",
            "restore_hash_matches": restored["identity"]["manifest_hash"]
            == first["manifest_hash"],
            "restore_did_not_overwrite_production": restored["production_overwritten"]
            is False,
        }
        payload = {
            "phase": 3,
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": checks,
            "passed": all(checks.values()),
            "manifest": {
                key: first[key]
                for key in (
                    "identity",
                    "identity_version",
                    "constitution_hash",
                    "identity_core_hash",
                    "schema_version",
                    "policy_version",
                    "manifest_hash",
                )
            },
            "restart": {
                "integrity": second["integrity"],
                "continuity_from_previous_run": second["continuity_from_previous_run"],
            },
            "tamper_probe": {
                "integrity": tampered["integrity"],
                "tamper_detected": tampered["tamper_detected"],
                "mismatches": tampered["mismatches"],
            },
            "restore_probe": {
                "status": restored["status"],
                "sqlite_integrity": restored["sqlite_integrity"],
                "production_overwritten": restored["production_overwritten"],
            },
        }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

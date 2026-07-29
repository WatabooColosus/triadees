"""Certificación de neuronas basada en evidencia completa y reversible."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = Path(__file__).resolve().parent.parent / "memory/schemas.sql"
MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "memory/migrations/028_neuron_certification.sql"
)
CERTIFIABLE_STATES = {
    "proposed",
    "candidate",
    "experimental",
    "evaluated",
    "verified",
    "stable",
    "degraded",
    "quarantined",
    "retired",
}


class NeuronCertifier:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.executescript(SCHEMA.read_text(encoding="utf-8"))
            conn.executescript(MIGRATION.read_text(encoding="utf-8"))

    def audit_stable(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT n.id, n.name, n.mission, n.domain, n.status,
                c.* FROM neurons n LEFT JOIN neuron_certifications c
                ON c.certification_id = (
                    SELECT c2.certification_id FROM neuron_certifications c2
                    WHERE c2.neuron_id=n.id ORDER BY c2.created_at DESC LIMIT 1)
                WHERE n.status='stable' ORDER BY n.id"""
            ).fetchall()
        results = []
        for row in rows:
            blockers = self._blockers(dict(row))
            results.append(
                {
                    "neuron_id": row["id"],
                    "name": row["name"],
                    "status": row["status"],
                    "certified": not blockers,
                    "blockers": blockers,
                    "recommended_status": "stable" if not blockers else "quarantined",
                }
            )
        return {
            "stable_count": len(results),
            "certified_count": sum(item["certified"] for item in results),
            "insufficient_count": sum(not item["certified"] for item in results),
            "neurons": results,
        }

    @staticmethod
    def _blockers(row: dict[str, Any]) -> list[str]:
        if row.get("certification_id") is None:
            return ["certification_manifest_missing"]
        blockers: list[str] = []
        required_text = (
            "version",
            "owner",
            "mission",
            "domain",
            "rollback_ref",
            "last_review",
        )
        blockers.extend(
            f"{field}_missing" for field in required_text if not row.get(field)
        )
        required_json = (
            "allowed_sources_json",
            "allowed_actions_json",
            "benchmarks_json",
            "baseline_json",
            "evidence_json",
            "limitations_json",
        )
        for field in required_json:
            try:
                if not json.loads(row.get(field) or "null"):
                    blockers.append(f"{field}_missing")
            except json.JSONDecodeError:
                blockers.append(f"{field}_invalid")
        gates = (
            "independent_evaluation",
            "regressions_green",
            "rollback_verified",
            "restart_verified",
            "benchmark_passed",
            "evidence_complete",
        )
        blockers.extend(f"{gate}_required" for gate in gates if row.get(gate) != 1)
        return blockers

    def apply_quarantine(self, backup_dir: str | Path) -> dict[str, Any]:
        report = self.audit_stable()
        backup_root = Path(backup_dir)
        backup_root.mkdir(parents=True, exist_ok=True)
        source_digest = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        backup = backup_root / f"neurons-pre-certification-{source_digest[:16]}.db"
        if not backup.exists():
            with (
                sqlite3.connect(self.db_path) as source,
                sqlite3.connect(backup) as target,
            ):
                source.backup(target)
        digest = hashlib.sha256(backup.read_bytes()).hexdigest()
        transitions = []
        with sqlite3.connect(self.db_path) as conn:
            for item in report["neurons"]:
                if item["certified"]:
                    continue
                transition_id = f"nct-{uuid.uuid4().hex}"
                rollback_ref = f"sqlite-backup:{backup}#sha256={digest}"
                conn.execute(
                    "UPDATE neurons SET status='quarantined', updated_at=? WHERE id=? AND status='stable'",
                    (datetime.now(UTC).isoformat(), item["neuron_id"]),
                )
                conn.execute(
                    "INSERT INTO neuron_certification_transitions VALUES (?, ?, 'stable', 'quarantined', ?, ?, ?)",
                    (
                        transition_id,
                        item["neuron_id"],
                        ";".join(item["blockers"]),
                        rollback_ref,
                        datetime.now(UTC).isoformat(),
                    ),
                )
                transitions.append(
                    {
                        **item,
                        "transition_id": transition_id,
                        "rollback_ref": rollback_ref,
                    }
                )
        return {
            **report,
            "backup": str(backup),
            "backup_sha256": digest,
            "applied_count": len(transitions),
            "transitions": transitions,
            "data_deleted": False,
            "identity_core_modified": False,
        }

    def restore_backup(self, backup_path: str | Path, expected_sha256: str) -> None:
        source = Path(backup_path)
        observed = hashlib.sha256(source.read_bytes()).hexdigest()
        if observed != expected_sha256:
            raise ValueError("neuron_certification_backup_hash_mismatch")
        with sqlite3.connect(source) as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("neuron_certification_backup_corrupt")
        with sqlite3.connect(source) as backup, sqlite3.connect(self.db_path) as target:
            backup.backup(target)

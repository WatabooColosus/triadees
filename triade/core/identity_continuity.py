"""Continuidad identitaria verificable, read-only sobre ``identity_core``."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triade.core.constitution import CONSTITUTION_VERSION, GLOBAL_CONSTITUTION
from triade.db import sqlite3

IDENTITY_NAME = "Triade Omega"
IDENTITY_VERSION = "1.0.0"
POLICY_VERSION = "TRIADE-IDENTITY-POLICY-v1"
DEFAULT_DB_PATH = Path("triade/memory/triade.db")
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "memory" / "migrations"
IDENTITY_MIGRATION = MIGRATIONS_DIR / "020_identity_continuity.sql"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class IdentityManifest:
    identity: str
    identity_version: str
    constitution_hash: str
    identity_core_hash: str
    schema_version: str
    policy_version: str
    manifest_hash: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class IdentityContinuity:
    """Calcula, ancla y verifica identidad sin escribir en ``identity_core``."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_base_schema()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_base_schema(self) -> None:
        schema = Path(__file__).resolve().parent.parent / "memory" / "schemas.sql"
        with self._connect() as conn:
            conn.executescript(schema.read_text(encoding="utf-8"))

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(IDENTITY_MIGRATION.read_text(encoding="utf-8"))

    def current_manifest(self) -> IdentityManifest:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT key, value, category, confidence
                FROM identity_core ORDER BY key"""
            ).fetchall()
        identity_core_hash = _canonical_hash([dict(row) for row in rows])
        constitution = GLOBAL_CONSTITUTION.to_dict()
        constitution_hash = _canonical_hash(constitution)
        versions = sorted(
            path.name.split("_", 1)[0]
            for path in MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")
        )
        schema_version = versions[-1] if versions else "000"
        values = {
            "identity": IDENTITY_NAME,
            "identity_version": IDENTITY_VERSION,
            "constitution_hash": constitution_hash,
            "identity_core_hash": identity_core_hash,
            "schema_version": schema_version,
            "policy_version": POLICY_VERSION,
        }
        return IdentityManifest(**values, manifest_hash=_canonical_hash(values))

    def verify(self, run_id: str | None = None, record: bool = True) -> dict[str, Any]:
        current = self.current_manifest()
        with self._connect() as conn:
            anchor = conn.execute(
                "SELECT * FROM identity_manifest_anchor WHERE singleton = 1"
            ).fetchone()
            if anchor is None:
                conn.execute(
                    """INSERT INTO identity_manifest_anchor
                    (singleton, identity, identity_version, constitution_hash,
                     identity_core_hash, schema_version, policy_version, manifest_hash,
                     established_at, established_by)
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        current.identity,
                        current.identity_version,
                        current.constitution_hash,
                        current.identity_core_hash,
                        current.schema_version,
                        current.policy_version,
                        current.manifest_hash,
                        _utc_now(),
                        "initial-verification",
                    ),
                )
                anchor = conn.execute(
                    "SELECT * FROM identity_manifest_anchor WHERE singleton = 1"
                ).fetchone()

            fields = (
                "identity",
                "identity_version",
                "constitution_hash",
                "identity_core_hash",
                "schema_version",
                "policy_version",
                "manifest_hash",
            )
            mismatches = [
                field
                for field in fields
                if str(anchor[field]) != str(getattr(current, field))
            ]
            prior = conn.execute(
                """SELECT manifest_hash, integrity FROM identity_continuity_log
                ORDER BY verified_at DESC LIMIT 1"""
            ).fetchone()
            integrity = "verified" if not mismatches else "degraded_safe"
            continuity = bool(
                prior is not None
                and prior["integrity"] == "verified"
                and prior["manifest_hash"] == current.manifest_hash
            )
            effective_run_id = run_id or f"identity-{uuid.uuid4().hex[:16]}"
            verified_at = _utc_now()
            if record:
                conn.execute(
                    """INSERT INTO identity_continuity_log
                    (verification_id, run_id, manifest_hash, expected_manifest_hash,
                     integrity, continuity_from_previous_run, tamper_detected,
                     mismatch_json, verified_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        f"iv-{uuid.uuid4().hex}",
                        effective_run_id,
                        current.manifest_hash,
                        anchor["manifest_hash"],
                        integrity,
                        int(continuity),
                        int(bool(mismatches)),
                        json.dumps(mismatches),
                        verified_at,
                    ),
                )
        return {
            **current.to_dict(),
            "constitution_version": CONSTITUTION_VERSION,
            "integrity": integrity,
            "continuity_from_previous_run": continuity,
            "tamper_detected": bool(mismatches),
            "degraded_mode": bool(mismatches),
            "mismatches": mismatches,
            "run_id": effective_run_id,
            "verified_at": verified_at,
        }

    def migrate_anchor(
        self, *, approved_by: str, reason: str, backup_dir: str | Path
    ) -> dict[str, Any]:
        if not approved_by.strip() or not reason.strip():
            raise ValueError("approved_by y reason explícitos son obligatorios")
        backup_root = Path(backup_dir)
        backup_root.mkdir(parents=True, exist_ok=True)
        backup = backup_root / f"identity-anchor-{uuid.uuid4().hex}.sqlite3"
        with self._connect() as source, sqlite3.connect(backup) as target:
            source.backup(target)
        current = self.current_manifest()
        with self._connect() as conn:
            conn.execute(
                """UPDATE identity_manifest_anchor SET
                identity = ?, identity_version = ?, constitution_hash = ?,
                identity_core_hash = ?, schema_version = ?, policy_version = ?,
                manifest_hash = ?, established_at = ?, established_by = ?, backup_ref = ?
                WHERE singleton = 1""",
                (
                    current.identity,
                    current.identity_version,
                    current.constitution_hash,
                    current.identity_core_hash,
                    current.schema_version,
                    current.policy_version,
                    current.manifest_hash,
                    _utc_now(),
                    approved_by,
                    str(backup),
                ),
            )
        result = self.verify(run_id=f"identity-migration-{uuid.uuid4().hex[:12]}")
        return {**result, "backup_ref": str(backup), "migration_reason": reason}

    def restore_to_sandbox(
        self, backup_ref: str | Path, target: str | Path
    ) -> dict[str, Any]:
        source = Path(backup_ref)
        destination = Path(target)
        if not source.is_file():
            raise FileNotFoundError(source)
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        with sqlite3.connect(destination) as conn:
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        verification = IdentityContinuity(destination).verify(record=False)
        return {
            "status": "verified"
            if integrity == "ok" and verification["integrity"] == "verified"
            else "failed",
            "sqlite_integrity": integrity,
            "identity": verification,
            "restored_path": str(destination),
            "production_overwritten": False,
        }

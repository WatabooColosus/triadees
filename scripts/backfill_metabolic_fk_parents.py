#!/usr/bin/env python3
"""Reconstruye padres metabólicos históricos sin borrar recibos.

El modo por defecto es ``dry-run``. ``--apply`` inserta únicamente padres que
pueden derivarse de recibos existentes y escribe un manifiesto reversible.
``--verify`` sólo mide; ``--rollback MANIFEST`` elimina exclusivamente las
filas creadas por ese manifiesto y restaura el estado previo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DB = Path("triade/memory/triade.db")
DEFAULT_MANIFEST_DIR = Path("artifacts/migrations")
MARKER = "metabolic_fk_parent_backfill_v1"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def _violations(connection: sqlite3.Connection) -> dict[str, Any]:
    rows = list(connection.execute("PRAGMA foreign_key_check"))
    by_relation: dict[str, int] = {}
    for row in rows:
        key = f"{row[0]}->{row[2]}"
        by_relation[key] = by_relation.get(key, 0) + 1
    return {"total": len(rows), "by_relation": by_relation}


def _missing_needs(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            """SELECT r.need_id, r.cycle_id, MIN(r.started_at) AS created_at,
                      COUNT(*) AS receipt_count,
                      MIN(r.receipt_id) AS evidence_receipt
               FROM metabolic_receipts r
               LEFT JOIN metabolic_needs n ON n.need_id=r.need_id
               WHERE n.need_id IS NULL
               GROUP BY r.need_id,r.cycle_id
               ORDER BY r.cycle_id,r.need_id"""
        )
    )


def _missing_cycles(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            """SELECT r.cycle_id, MIN(r.started_at) AS started_at,
                      MAX(COALESCE(r.finished_at,r.started_at)) AS finished_at,
                      COUNT(*) AS receipt_count
               FROM metabolic_receipts r
               LEFT JOIN metabolic_cycle c ON c.cycle_id=r.cycle_id
               WHERE c.cycle_id IS NULL
               GROUP BY r.cycle_id ORDER BY r.cycle_id"""
        )
    )


def inspect(db_path: Path) -> dict[str, Any]:
    with _connect(db_path) as connection:
        needs = _missing_needs(connection)
        cycles = _missing_cycles(connection)
        return {
            "status": "measured",
            "db_path": str(db_path),
            "violations": _violations(connection),
            "missing_need_parents": len(needs),
            "missing_cycle_parents": len(cycles),
            "cycle_ids": [int(row["cycle_id"]) for row in cycles],
            "first_missing_need": str(needs[0]["need_id"]) if needs else None,
            "last_missing_need": str(needs[-1]["need_id"]) if needs else None,
        }


def _kind(need_id: str) -> str:
    prefix, separator, suffix = need_id.rpartition("-")
    return prefix if separator and len(suffix) >= 8 else need_id


def apply(db_path: Path, manifest_dir: Path) -> dict[str, Any]:
    started_at = _now()
    manifest_dir.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as connection:
        before = _violations(connection)
        needs = _missing_needs(connection)
        cycles = _missing_cycles(connection)
        with connection:
            for row in cycles:
                evidence = json.dumps(
                    {
                        "backfill": MARKER,
                        "receipt_count": int(row["receipt_count"]),
                        "reason": "parent reconstructed from preserved historical receipts",
                    },
                    sort_keys=True,
                )
                connection.execute(
                    """INSERT INTO metabolic_cycle
                       (cycle_id,started_at,finished_at,status,mode,error,summary_json)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        int(row["cycle_id"]),
                        str(row["started_at"]),
                        str(row["finished_at"]),
                        "historical_receipt_only",
                        "historical",
                        None,
                        evidence,
                    ),
                )
            for row in needs:
                need_id = str(row["need_id"])
                evidence = json.dumps(
                    {
                        "backfill": MARKER,
                        "evidence_receipt": str(row["evidence_receipt"]),
                        "receipt_count": int(row["receipt_count"]),
                        "reason": "parent reconstructed from preserved historical receipt",
                    },
                    sort_keys=True,
                )
                connection.execute(
                    """INSERT INTO metabolic_needs
                       (need_id,cycle_id,kind,priority,evidence_json,
                        estimated_cost_json,risk,status,authorization_policy,
                        success_condition,created_at,finished_at,result_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        need_id,
                        int(row["cycle_id"]),
                        _kind(need_id),
                        0,
                        evidence,
                        "{}",
                        "unknown",
                        "historical_receipt_only",
                        "never",
                        "preserve referential history only",
                        str(row["created_at"]),
                        str(row["created_at"]),
                        json.dumps({"backfill": MARKER}, sort_keys=True),
                    ),
                )
        after = _violations(connection)

    manifest: dict[str, Any] = {
        "version": 1,
        "marker": MARKER,
        "db_path": str(db_path),
        "started_at": started_at,
        "finished_at": _now(),
        "before": before,
        "after": after,
        "inserted_cycle_ids": [int(row["cycle_id"]) for row in cycles],
        "inserted_need_ids": [str(row["need_id"]) for row in needs],
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    manifest["manifest_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    manifest_path = (
        manifest_dir / f"metabolic-fk-backfill-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest_path.chmod(0o600)
    return {"status": "applied", "manifest": str(manifest_path), **manifest}


def rollback(db_path: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("marker") != MARKER:
        raise ValueError("manifest_marker_mismatch")
    need_ids = [str(value) for value in manifest.get("inserted_need_ids", [])]
    cycle_ids = [int(value) for value in manifest.get("inserted_cycle_ids", [])]
    with _connect(db_path) as connection:
        before = _violations(connection)
        connection.execute("PRAGMA foreign_keys=OFF")
        with connection:
            for need_id in need_ids:
                row = connection.execute(
                    "SELECT evidence_json FROM metabolic_needs WHERE need_id=?",
                    (need_id,),
                ).fetchone()
                if row and json.loads(str(row[0] or "{}")).get("backfill") == MARKER:
                    connection.execute(
                        "DELETE FROM metabolic_needs WHERE need_id=?", (need_id,)
                    )
            for cycle_id in cycle_ids:
                row = connection.execute(
                    "SELECT summary_json FROM metabolic_cycle WHERE cycle_id=?",
                    (cycle_id,),
                ).fetchone()
                if row and json.loads(str(row[0] or "{}")).get("backfill") == MARKER:
                    connection.execute(
                        "DELETE FROM metabolic_cycle WHERE cycle_id=?", (cycle_id,)
                    )
        after = _violations(connection)
    return {"status": "rolled_back", "before": before, "after": after}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--rollback", type=Path)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    args = parser.parse_args()
    if args.rollback:
        result = rollback(args.db, args.rollback)
    elif args.apply:
        result = apply(args.db, args.manifest_dir)
    else:
        result = inspect(args.db)
        result["mode"] = "verify" if args.verify else "dry-run"
    if result.get("status") == "applied":
        result = {
            "status": result["status"],
            "manifest": result["manifest"],
            "manifest_sha256": result["manifest_sha256"],
            "before": result["before"],
            "after": result["after"],
            "inserted_cycles": len(result["inserted_cycle_ids"]),
            "inserted_needs": len(result["inserted_need_ids"]),
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

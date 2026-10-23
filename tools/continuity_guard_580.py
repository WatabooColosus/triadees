"""Read-only Tríade 5.8 continuity gate for SQLite DBs and Drive memory ZIPs.

Never restores, merges, overwrites or restarts a live runtime. Compares stable
record identifiers rather than a table's mere existence or a process heartbeat.
Outputs aggregated counts only; no prompts, auth records or neuron text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any

KEYS = {
    "neurons": "name",
    "autonomous_tasks": "task_id",
    "neuron_education_sessions": "session_id",
    "neuron_education_applications": "id",
    "learning_queue": "candidate_id",
    "triade_weight_events": "event_id",
    "governed_research_runs": "research_id",
}
ZIP_DB = "repo/triade/memory/triade.db"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _open_snapshot(path: Path, target: Path) -> dict[str, Any]:
    """Create a consistent *temporary* backup without mutating the source DB."""
    extra: dict[str, Any] = {"source_type": "sqlite", "archive_sha256": None}
    if zipfile.is_zipfile(path):
        extra["source_type"] = "drive_memory_v2_zip"
        extra["archive_sha256"] = _sha256(path)
        with zipfile.ZipFile(path) as archive:
            if ZIP_DB not in archive.namelist():
                raise ValueError("archive_missing_canonical_sqlite")
            with archive.open(ZIP_DB) as src, target.open("wb") as dest:
                for block in iter(lambda: src.read(1024 * 1024), b""):
                    dest.write(block)
    else:
        if not path.is_file() or path.resolve() == target.resolve():
            raise ValueError("missing_or_invalid_sqlite_source")
        # No immutable=1, because a live WAL database must be read consistently.
        with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=10) as src:
            with sqlite3.connect(target) as copy:
                src.backup(copy)
    return extra


def _read_snapshot(path: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="triade-continuity-") as directory:
        temp = Path(directory) / "snapshot.sqlite3"
        meta = _open_snapshot(path, temp)
        with sqlite3.connect(f"{temp.as_uri()}?mode=ro", uri=True) as db:
            check = db.execute("PRAGMA integrity_check(1)").fetchone()[0]
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            counts: dict[str, int | None] = {}
            identities: dict[str, set[str] | None] = {}
            for table, key in KEYS.items():
                if table not in tables:
                    counts[table], identities[table] = None, None
                    continue
                # Check schema before selecting an identifier, and fail closed
                # rather than pretending an incompatible table has no rows.
                columns = {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
                if key not in columns:
                    counts[table], identities[table] = None, None
                    continue
                ids = {str(r[0]) for r in db.execute(f'SELECT "{key}" FROM "{table}" WHERE "{key}" IS NOT NULL')}
                counts[table] = db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                identities[table] = ids
            return {"meta": meta, "quick_check": check, "table_count": len(tables), "counts": counts, "identities": identities}


def compare(reference: Path, candidate: Path) -> dict[str, Any]:
    base, new = _read_snapshot(reference), _read_snapshot(candidate)
    measures: dict[str, Any] = {}
    blocking: list[str] = []
    for table in KEYS:
        a, b = base["identities"][table], new["identities"][table]
        if a is None or b is None:
            measures[table] = {"reference": base["counts"][table], "candidate": new["counts"][table], "shared": None, "missing_from_candidate": None}
            if a is not None and len(a):
                blocking.append(f"missing_table_or_key:{table}")
            continue
        shared = len(a & b)
        missing = len(a - b)
        measures[table] = {"reference": base["counts"][table], "candidate": new["counts"][table], "shared": shared, "missing_from_candidate": missing}
        if missing:
            blocking.append(f"historical_ids_absent:{table}")
    if base["quick_check"] != "ok" or new["quick_check"] != "ok":
        blocking.append("sqlite_integrity_check_failed")
    return {
        "schema": "triade-continuity-gate-v1",
        "state": "BLOCK_RESTORE_OR_PROMOTION" if blocking else "IDENTITIES_PRESERVED",
        "certifies_full_restore": False,  # External file packs not examined here.
        "mutates_runtime": False,
        "reference": {"source_type": base["meta"]["source_type"], "archive_sha256": base["meta"]["archive_sha256"], "sqlite_check": base["quick_check"], "table_count": base["table_count"]},
        "candidate": {"source_type": new["meta"]["source_type"], "archive_sha256": new["meta"]["archive_sha256"], "sqlite_check": new["quick_check"], "table_count": new["table_count"]},
        "tables": measures,
        "blocking_reasons": blocking,
        "next_action": "isolate_and_reconcile_offline; do_not_overwrite_live_sqlite" if blocking else "verify_external_packs_and_colab_live_acceptance",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True, help="Historical Drive ZIP or SQLite snapshot")
    parser.add_argument("--candidate", type=Path, required=True, help="New backup or running SQLite database")
    parser.add_argument("--report", type=Path, help="Optional JSON report (never DB contents)")
    args = parser.parse_args()
    if args.reference.resolve() == args.candidate.resolve():
        parser.error("reference_and_candidate_must_differ")
    try:
        result = compare(args.reference, args.candidate)
    except (OSError, sqlite3.Error, ValueError, zipfile.BadZipFile) as exc:
        result = {"schema": "triade-continuity-gate-v1", "state": "BLOCK_RESTORE_OR_PROMOTION", "error_type": type(exc).__name__, "mutates_runtime": False}
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.report:
        if args.report.exists():
            parser.error("report_exists_refusing_overwrite")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as report:
            report.write(payload + "\n")
    print(payload)
    return 0 if result["state"] == "IDENTITIES_PRESERVED" else 2


if __name__ == "__main__":
    raise SystemExit(main())

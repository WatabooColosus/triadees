"""Audita y, con `--apply`, resuelve goals históricos en limbo.

No borra filas. El artefacto conserva el estado anterior y genera sentencias de
rollback exactas para las únicas columnas que modifica la política.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from triade.core.planning_graph import PlanningGraph

ACTIVE = ("pending", "awaiting_approval", "queued", "running", "replanning")


def _sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _candidates(db_path: Path, max_age_minutes: int) -> list[dict[str, Any]]:
    cutoff = (datetime.now(UTC) - timedelta(minutes=max_age_minutes)).isoformat()
    placeholders = ",".join("?" for _ in ACTIVE)
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        roots = conn.execute(
            f"""SELECT * FROM planning_graph
            WHERE parent_id IS NULL AND status IN ({placeholders}) AND updated_at < ?
            ORDER BY created_at""",
            (*ACTIVE, cutoff),
        ).fetchall()
        rows: list[sqlite3.Row] = []
        for root in roots:
            rows.append(root)
            rows.extend(
                conn.execute(
                    "SELECT * FROM planning_graph WHERE parent_id=? ORDER BY created_at",
                    (root["goal_id"],),
                ).fetchall()
            )
    return [dict(row) for row in rows]


def run(
    db_path: Path, *, apply: bool, max_age_minutes: int, actor: str
) -> dict[str, Any]:
    before = _candidates(db_path, max_age_minutes)
    report: dict[str, Any] = {
        "mode": "apply" if apply else "dry_run",
        "policy": "expire_nonterminal_root_and_children_after_max_age",
        "max_age_minutes": max_age_minutes,
        "actor": actor,
        "before": before,
        "root_goal_ids": [row["goal_id"] for row in before if row["parent_id"] is None],
    }
    if apply:
        report["reconciliation"] = PlanningGraph(db_path).reconcile_limbo(
            max_age_minutes=max_age_minutes, actor=actor
        )
    ids = [str(row["goal_id"]) for row in before]
    after: list[dict[str, Any]] = []
    if ids:
        placeholders = ",".join("?" for _ in ids)
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            after = [
                dict(row)
                for row in conn.execute(
                    f"SELECT * FROM planning_graph WHERE goal_id IN ({placeholders}) ORDER BY created_at",
                    ids,
                )
            ]
    report["after"] = after
    report["rollback_sql"] = [
        "UPDATE planning_graph SET status={status}, updated_at={updated}, completed_at={completed} WHERE goal_id={goal};".format(
            status=json.dumps(str(row["status"])),
            updated=json.dumps(str(row["updated_at"])),
            completed="NULL"
            if row["completed_at"] is None
            else json.dumps(str(row["completed_at"])),
            goal=json.dumps(str(row["goal_id"])),
        )
        for row in before
    ]
    report["rollback_sql"].append(
        f"DELETE FROM goal_events WHERE actor={json.dumps(actor)};"
    )
    report.update(
        {
            "sha": _sha(),
            "generated_at": datetime.now(UTC).isoformat(),
            "database": str(db_path),
            "rows_preserved": len(before),
            "rows_deleted": 0,
        }
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("triade/memory/triade.db"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-age-minutes", type=int, default=60)
    parser.add_argument("--actor", default="phase3:goal-limbo-policy")
    args = parser.parse_args()
    result = run(
        args.db,
        apply=args.apply,
        max_age_minutes=max(1, args.max_age_minutes),
        actor=args.actor,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

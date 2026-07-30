#!/usr/bin/env python3
"""Registra resultados GitHub Actions del SHA actual sin fabricar aprobación."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REQUIRED_WORKFLOWS = {
    "Runtime Truth CI",
    "Tríade Tests",
    "Measurement Core",
    "Python Tests",
}


def _git_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def collect() -> dict[str, object]:
    sha = _git_sha()
    result = subprocess.run(
        [
            "gh",
            "run",
            "list",
            "--commit",
            sha,
            "--limit",
            "20",
            "--json",
            "name,status,conclusion,url,headSha,databaseId",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    runs = json.loads(result.stdout)
    workflows = [
        item
        for item in runs
        if isinstance(item, dict)
        and item.get("headSha") == sha
        and item.get("name") in REQUIRED_WORKFLOWS
    ]
    successful = {
        str(item["name"])
        for item in workflows
        if item.get("status") == "completed" and item.get("conclusion") == "success"
    }
    return {
        "phase": 18,
        "sha": sha,
        "required_workflows": sorted(REQUIRED_WORKFLOWS),
        "workflows": workflows,
        "passed": successful == REQUIRED_WORKFLOWS,
        "recorded_at": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    evidence = collect()
    target = Path("artifacts/triade_verify/phase_18/ci.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence, indent=2, ensure_ascii=False))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

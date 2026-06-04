"""Informacion local del repositorio Git."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def repo_info(cwd: str | Path = ".") -> dict[str, Any]:
    root = Path(cwd)
    origin = _git(["remote", "get-url", "origin"], root)
    branch = _git(["branch", "--show-current"], root)
    commit = _git(["rev-parse", "--short", "HEAD"], root)
    upstream = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], root)
    status = _git(["status", "--short"], root)
    return {
        "status": "ok" if commit else "unavailable",
        "root": str(root.resolve()),
        "origin": origin or None,
        "branch": branch or None,
        "commit": commit or None,
        "upstream": upstream or None,
        "dirty": bool(status),
        "changed_files": len(status.splitlines()) if status else 0,
    }


def _git(args: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()

"""Capture release provenance once, at process bootstrap, never at polling time."""

from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SOURCE_PATHS = (
    "triade",
    "apps",
    "scripts",
    "frontend",
    "tests",
    "triade.yml",
    "pyproject.toml",
    "requirements.txt",
)


def capture_source(root: Path) -> dict:
    result: dict[str, Any] = {
        "captured_at": datetime.now(UTC).isoformat(),
        "status": "UNVERIFIED",
    }
    try:

        def git(*args: str) -> str:
            return subprocess.check_output(
                ["git", *args],
                cwd=root,
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).strip()

        sha = git("rev-parse", "HEAD")
        dirty = bool(
            git(
                "status", "--porcelain", "--untracked-files=normal", "--", *SOURCE_PATHS
            )
        )
        digest = hashlib.sha256()
        for name in sorted(git("ls-files", "--", *SOURCE_PATHS).splitlines()):
            path = root / name
            if path.is_file() and path.suffix in {
                ".py",
                ".ps1",
                ".cmd",
                ".js",
                ".ts",
                ".tsx",
                ".json",
                ".yml",
                ".yaml",
                ".sql",
                ".toml",
                ".css",
                ".txt",
            }:
                digest.update(name.encode())
                digest.update(path.read_bytes())
        result.update(
            {
                "git_sha": sha,
                "source_dirty": dirty,
                "source_hash": digest.hexdigest(),
                "status": "CLEAN" if not dirty else "DIRTY",
            }
        )
    except (OSError, subprocess.SubprocessError) as exc:
        result["reason"] = type(exc).__name__
    return result


def bind_loaded_source(before: dict, after: dict) -> dict:
    verified = (
        before.get("status") == after.get("status") == "CLEAN"
        and before.get("git_sha") == after.get("git_sha")
        and before.get("source_hash") == after.get("source_hash")
    )
    return {
        **after,
        "status": "VERIFIED_AT_BOOTSTRAP" if verified else "UNVERIFIED",
        "bootstrap_before": before,
        "verified": verified,
    }

"""Estado del repositorio y runtime para la cabina React viva.

Usa comandos git whitelist con shell=False y timeout.
No ejecuta comandos arbitrarios del usuario.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _run_git(args: list[str], timeout: float = 3.0) -> str | None:
    try:
        return subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=timeout,
            shell=False,
        ).stdout.strip()
    except Exception:
        return None


def build_repo_runtime_status() -> dict[str, Any]:
    """Estado Git del repositorio + runtime interno.

    Solo comandos whitelist, shell=False, timeout 3s.
    """
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    commit = _run_git(["rev-parse", "--short", "HEAD"])
    raw_status = _run_git(["status", "--short"])
    raw_log = _run_git(["log", "-5", "--pretty=format:%h|%ad|%s", "--date=iso"])

    changed_files = []
    dirty = False
    if raw_status:
        for line in raw_status.splitlines():
            line = line.strip()
            if line:
                changed_files.append(line)
                dirty = True

    recent_commits = []
    if raw_log:
        for line in raw_log.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                recent_commits.append({
                    "hash": parts[0],
                    "date": parts[1],
                    "message": parts[2],
                })

    if branch is None and commit is None:
        return {
            "status": "unavailable",
            "error": "No se pudo leer estado del repositorio (git no disponible o no es un repo).",
        }

    return {
        "status": "ok",
        "branch": branch or "unknown",
        "commit": commit or "unknown",
        "dirty": dirty,
        "changed_files_count": len(changed_files),
        "changed_files": changed_files[:50],
        "recent_commits": recent_commits,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

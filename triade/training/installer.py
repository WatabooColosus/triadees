"""Instalación reversible en un venv por objetivo, siempre con aprobación humana."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import time
import venv
from pathlib import Path
from typing import Any

PACKAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?(?:==[A-Za-z0-9_.+!-]+)?$")


class IsolatedInstaller:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db", root: str | Path = "artifacts/environments") -> None:
        self.db_path, self.root = Path(db_path), Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS installer_attempts(
                id INTEGER PRIMARY KEY AUTOINCREMENT, goal_id TEXT, package TEXT, approved_by TEXT,
                started_at TEXT DEFAULT CURRENT_TIMESTAMP, finished_at TEXT, status TEXT, environment TEXT,
                manifest_sha256 TEXT, error TEXT)""")

    def install(self, package: str, *, goal_id: str, approved: bool, approved_by: str) -> dict[str, Any]:
        if not approved or not approved_by:
            return {"status": "blocked", "reason": "explicit_human_approval_required"}
        if not PACKAGE.fullmatch(package):
            return {"status": "blocked", "reason": "invalid_or_unpinned_package_spec"}
        safe_goal = re.sub(r"[^A-Za-z0-9_.-]", "-", goal_id)[:80]
        env = (self.root / safe_goal).resolve()
        if self.root.resolve() not in env.parents:
            return {"status": "blocked", "reason": "environment_path_escape"}
        with sqlite3.connect(self.db_path) as conn:
            attempt = conn.execute(
                "INSERT INTO installer_attempts(goal_id,package,approved_by,status,environment) VALUES(?,?,?,?,?)",
                (goal_id, package, approved_by, "running", str(env)),
            ).lastrowid
        try:
            venv.EnvBuilder(with_pip=True, clear=False).create(env)
            python = env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            result = subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", package],
                                    capture_output=True, text=True, timeout=600, shell=False)
            if result.returncode:
                raise RuntimeError((result.stderr or result.stdout)[-1500:])
            frozen = subprocess.run([str(python), "-m", "pip", "freeze", "--all"], capture_output=True,
                                    text=True, timeout=60, shell=False, check=True).stdout
            manifest = {"goal_id": goal_id, "package": package, "approved_by": approved_by,
                        "environment": str(env), "freeze": frozen.splitlines(), "created_at": time.time(),
                        "rollback": {"action": "quarantine_environment", "automatic_activation": False}}
            encoded = json.dumps(manifest, sort_keys=True).encode(); digest = hashlib.sha256(encoded).hexdigest()
            (env / "triade-install-manifest.json").write_text(json.dumps({**manifest, "sha256": digest}, indent=2), encoding="utf-8")
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("UPDATE installer_attempts SET status='installed_isolated',finished_at=CURRENT_TIMESTAMP,manifest_sha256=? WHERE id=?", (digest, attempt))
            return {"status": "completed", "environment": str(env), "manifest_sha256": digest,
                    "activated_in_production": False, "rollback_ready": True}
        except Exception as exc:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("UPDATE installer_attempts SET status='failed',finished_at=CURRENT_TIMESTAMP,error=? WHERE id=?", (str(exc), attempt))
            return {"status": "error", "error": str(exc), "environment": str(env), "activated_in_production": False}


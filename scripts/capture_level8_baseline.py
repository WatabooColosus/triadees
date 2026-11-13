"""Read-only Windows/local baseline; records observations, not certification."""

from __future__ import annotations

import json
import platform
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
TRIADE_ENTRYPOINT_KIND = "manual_diagnostic"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def capture():
    import psutil

    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "git_status": git("status", "--short"),
        "origin_main": git("rev-parse", "origin/main"),
        "python_version": sys.version,
        "platform": platform.platform(),
        "ram": dict(psutil.virtual_memory()._asdict()),
        "workflows": [
            str(p.relative_to(ROOT)) for p in (ROOT / ".github/workflows").glob("*.yml")
        ],
        "tests_available": len(list((ROOT / "tests").rglob("test_*.py"))),
        "dependencies": {},
        "endpoints": {},
    }
    for name in ("pytest", "fastapi", "pydantic", "httpx", "psutil", "cryptography"):
        try:
            report["dependencies"][name] = version(name)
        except PackageNotFoundError:
            report["dependencies"][name] = "MISSING"
    db_path = ROOT / "triade/memory/triade.db"
    with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as db:
        report["database"] = {
            "path": str(db_path),
            "bytes": db_path.stat().st_size,
            "integrity": [r[0] for r in db.execute("PRAGMA integrity_check")],
            "journal_mode": db.execute("PRAGMA journal_mode").fetchone()[0],
            "tables": db.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0],
            "foreign_key_violations": len(
                db.execute("PRAGMA foreign_key_check").fetchall()
            ),
        }
    for path in (
        "/api/health",
        "/health/deep",
        "/api/runtime/heartbeat",
        "/api/runtime/metabolism/status",
    ):
        try:
            with urlopen("http://127.0.0.1:8010" + path, timeout=10) as response:
                report["endpoints"][path] = {
                    "http_status": response.status,
                    "body": json.load(response),
                }
        except (URLError, OSError, ValueError, TimeoutError) as exc:
            report["endpoints"][path] = {"error": str(exc)}
    gpu = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,temperature.gpu",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    report["gpu"] = {"exit_code": gpu.returncode, "measurement": gpu.stdout.strip()}
    return report


if __name__ == "__main__":
    result = capture()
    target = ROOT / "reports/level8/baseline.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(target)

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_runtime_cli_status_and_once(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"

    status = subprocess.run(
        [sys.executable, "triade_digimon.py", "runtime", "status", "--db", str(db_path), "--runs-dir", str(runs_dir)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    once = subprocess.run(
        [sys.executable, "triade_digimon.py", "runtime", "once", "--db", str(db_path), "--runs-dir", str(runs_dir), "--mode", "observe_only"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert status.returncode == 0, status.stderr
    assert once.returncode == 0, once.stderr
    assert "observe_only" in status.stdout
    assert "\"status\": \"ok\"" in once.stdout


from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import httpx

from triade_digimon import _live_runtime_diagnostic


def test_runtime_cli_status_and_once(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"

    status = subprocess.run(
        [
            sys.executable,
            "triade_digimon.py",
            "runtime",
            "status",
            "--db",
            str(db_path),
            "--runs-dir",
            str(runs_dir),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    once = subprocess.run(
        [
            sys.executable,
            "triade_digimon.py",
            "runtime",
            "once",
            "--db",
            str(db_path),
            "--runs-dir",
            str(runs_dir),
            "--mode",
            "observe_only",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert status.returncode == 0, status.stderr
    assert once.returncode == 0, once.stderr
    assert "observe_only" in status.stdout
    assert '"status": "ok"' in once.stdout


def test_live_runtime_diagnostic_marks_authoritative_source(monkeypatch):
    def fake_get(url, *, params, timeout):
        assert url == "http://127.0.0.1:8010/health/deep"
        assert params == {"limit": 7}
        assert timeout == 60.0
        return httpx.Response(
            200,
            json={"status": "ok", "mode": "full_local_guarded"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    result = _live_runtime_diagnostic("/health/deep", params={"limit": 7})

    assert result == {
        "status": "ok",
        "mode": "full_local_guarded",
        "diagnostic_source": "live_runtime_api",
    }

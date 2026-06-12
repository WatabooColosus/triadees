"""Tests para comandos CLI qualia de triade_digimon.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "triade_digimon.py", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_qualia_state_command(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    result = run_cli("qualia", "--db", str(db), "state")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "status" in payload


def test_qualia_experiences_command(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    result = run_cli("qualia", "--db", str(db), "experiences")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "experiences" in payload
    assert len(payload["experiences"]) == 0


def test_qualia_report_command(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    result = run_cli("qualia", "--db", str(db), "report")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "counts" in payload
    assert "latest_state" in payload


def test_qualia_publish_test_command(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    result = run_cli("qualia", "--db", str(db), "publish-test")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert "bundle" in payload


def test_qualia_publish_test_with_learning(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    result = run_cli(
        "qualia", "--db", str(db), "publish-test",
        "--proposed-learning", "Aprendizaje de prueba CLI.",
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["learning"] is not None
    assert payload["learning"]["source_type"] == "qualia_bus"


def test_qualia_experiences_after_publish(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    run_cli("qualia", "--db", str(db), "publish-test", "--observation", "obs cli test")
    result = run_cli("qualia", "--db", str(db), "experiences")
    payload = json.loads(result.stdout)
    assert len(payload["experiences"]) >= 1


def test_qualia_state_after_publish(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    run_cli("qualia", "--db", str(db), "publish-test")
    result = run_cli("qualia", "--db", str(db), "state")
    payload = json.loads(result.stdout)
    assert payload["state"] is not None

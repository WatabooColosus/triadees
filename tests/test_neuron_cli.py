"""Tests del CLI de neuronas."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "triade_digimon.py"


def run_cli(*args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_neuron_cli_create_list_show(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"

    created = run_cli(
        "neuron",
        "--db",
        str(db_path),
        "create",
        "--name",
        "Neurona CLI",
        "--mission",
        "Crear una neurona desde CLI para validar persistencia interna.",
        "--domain",
        "cli-test",
        "--rule",
        "Debe ser verificable.",
    )

    assert created["status"] == "ok"
    assert created["neuron_id"] > 0
    assert created["training_id"] > 0

    listed = run_cli("neuron", "--db", str(db_path), "list", "--limit", "5")
    assert listed["status"] == "ok"
    assert any(item["name"] == "Neurona CLI" for item in listed["neurons"])

    shown = run_cli("neuron", "--db", str(db_path), "show", "Neurona CLI")
    assert shown["status"] == "ok"
    assert shown["neuron"]["name"] == "Neurona CLI"
    assert shown["training"]


def test_neuron_cli_show_not_found(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"

    shown = run_cli("neuron", "--db", str(db_path), "show", "No Existe")

    assert shown["status"] == "not_found"

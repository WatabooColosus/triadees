from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from triade.core.neuron_creator import NeuronSpec
from triade.core.neuron_registry import NeuronRegistry


_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", _PROJECT_ROOT)
    return env


def write_activity(run_path: Path, *, name: str = "neurona-test-stable", marker: int = 1) -> None:
    run_path.mkdir(parents=True, exist_ok=True)
    activity = {
        "active": True,
        "count": 1,
        "activations": [
            {
                "neuron_id": 1,
                "name": name,
                "status": "experimental",
                "domain": "system_governance",
                "match": {"active": True, "reasons": [f"test-{marker}"]},
                "output": {
                    "diagnosis": ["d1", "d2"],
                    "test_plan": ["t1"],
                },
                "policy": "experimental_neuron_no_external_actions_no_stable_memory_write",
            }
        ],
    }
    (run_path / "experimental_neuron_activity.json").write_text(
        json.dumps(activity, ensure_ascii=False),
        encoding="utf-8",
    )


def seed_neuron(db_path: Path, *, name: str = "neurona-test-stable", status: str = "experimental") -> None:
    registry = NeuronRegistry(db_path=db_path)
    registry.register(NeuronSpec(
        name=name,
        mission="Probar promoción estable controlada.",
        domain="system_governance",
        rules=["Solo promoción con evidencia y humano."],
        status=status,
        created_by="test",
    ))


def run_promote(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/promote_neuron_stable.py", *args],
        capture_output=True,
        text=True,
        check=False,
        env=_env(),
    )


def test_stable_promotion_requires_human_confirmation(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    decisions_path = tmp_path / "stable_promotion_decisions.json"

    seed_neuron(db_path)
    for i in range(5):
        write_activity(runs_dir / f"run-test-{i:03d}", marker=i)

    result = run_promote([
        "neurona-test-stable",
        "--db-path", str(db_path),
        "--runs-dir", str(runs_dir),
        "--decisions-path", str(decisions_path),
    ])

    assert result.returncode != 0
    assert "requiere --confirm-human" in (result.stderr + result.stdout)

    neuron = NeuronRegistry(db_path=db_path).get_neuron("neurona-test-stable")
    assert neuron is not None
    assert neuron["status"] == "experimental"


def test_stable_promotion_blocks_when_not_ready(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    decisions_path = tmp_path / "stable_promotion_decisions.json"

    seed_neuron(db_path)
    write_activity(runs_dir / "run-test-001")

    result = run_promote([
        "neurona-test-stable",
        "--db-path", str(db_path),
        "--runs-dir", str(runs_dir),
        "--decisions-path", str(decisions_path),
        "--confirm-human",
        "--reason", "Intento de prueba sin evidencia suficiente.",
    ])

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["blocked"] is True
    assert payload["decision"]["decision"] == "blocked_not_ready"
    assert payload["decision"]["next_status"] == "experimental"

    neuron = NeuronRegistry(db_path=db_path).get_neuron("neurona-test-stable")
    assert neuron is not None
    assert neuron["status"] == "experimental"

    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    assert decisions[-1]["decision"] == "blocked_not_ready"


def test_stable_promotion_blocks_non_experimental_status(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    decisions_path = tmp_path / "stable_promotion_decisions.json"

    seed_neuron(db_path, status="candidate")
    for i in range(5):
        write_activity(runs_dir / f"run-test-{i:03d}", marker=i)

    result = run_promote([
        "neurona-test-stable",
        "--db-path", str(db_path),
        "--runs-dir", str(runs_dir),
        "--decisions-path", str(decisions_path),
        "--confirm-human",
    ])

    assert result.returncode != 0
    assert "solo se promueven neuronas experimental" in (result.stderr + result.stdout).lower()

    neuron = NeuronRegistry(db_path=db_path).get_neuron("neurona-test-stable")
    assert neuron is not None
    assert neuron["status"] == "candidate"


def test_stable_promotion_succeeds_when_ready_and_confirmed(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    decisions_path = tmp_path / "stable_promotion_decisions.json"

    seed_neuron(db_path)
    for i in range(5):
        write_activity(runs_dir / f"run-test-{i:03d}", marker=i)

    result = run_promote([
        "neurona-test-stable",
        "--db-path", str(db_path),
        "--runs-dir", str(runs_dir),
        "--decisions-path", str(decisions_path),
        "--confirm-human",
        "--reason", "Evidencia suficiente y revisión humana aprobada.",
    ])

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["decision"]["decision"] == "promote_to_stable"
    assert payload["decision"]["previous_status"] == "experimental"
    assert payload["decision"]["next_status"] == "stable"

    neuron = NeuronRegistry(db_path=db_path).get_neuron("neurona-test-stable")
    assert neuron is not None
    assert neuron["status"] == "stable"

    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    assert decisions[-1]["decision"] == "promote_to_stable"
    assert decisions[-1]["policy"] == "stable_requires_evidence_and_explicit_human_confirmation"

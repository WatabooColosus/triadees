from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from triade.core.neuron_creator import NeuronSpec
from triade.core.neuron_registry import NeuronRegistry
from triade.core.primary_neuron_pipeline import build_primary_neuron_package


_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", _PROJECT_ROOT)
    return env


def test_primary_neuron_package_has_complete_contract() -> None:
    package = build_primary_neuron_package(
        name="neurona-verifica-estado-actual",
        mission="Verifica estado actual de neuronas candidatas, pulso Android y pipeline Creadora Formadora.",
        domain="build_or_update",
        source_run="run-test",
        user_text="Verifica estado actual de neuronas candidatas, pulso Android y pipeline Creadora Formadora.",
        intent="build_or_update",
        context={},
    )

    assert package["registered_as"] == "candidate"
    assert package["activation"] == "auto_approved"
    assert package["proposal_quality"]["contract_complete"] is True
    assert package["proposal_quality"]["required_human_review"] is False
    assert package["activation_policy"]["auto_stable_allowed"] is True
    assert package["activation_policy"]["auto_experimental_allowed"] is True
    assert package["assessment"]["warnings"] == []
    assert package["assessment"]["score"] >= 0.8

    contracts = package["contracts"]
    assert contracts["inputs_allowed"]
    assert contracts["outputs_allowed"]
    assert contracts["forbidden_actions"]
    assert package["success_metrics"]
    assert package["evidence_required"]


def test_primary_neuron_forbidden_actions_are_deduplicated() -> None:
    package = build_primary_neuron_package(
        name="neurona-verifica-estado-actual",
        mission="Verifica estado actual de neuronas candidatas, pulso Android y pipeline Creadora Formadora.",
        domain="build_or_update",
        source_run="run-test",
        user_text="Verifica estado actual de neuronas candidatas, pulso Android y pipeline Creadora Formadora.",
        intent="build_or_update",
        context={},
    )

    actions = package["contracts"]["forbidden_actions"]
    assert len(actions) == len(set(actions))
    assert "self_promote_to_stable" in actions
    assert "bypass_safety" in actions


def test_registry_deduplicates_rules_and_updates_status(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    registry = NeuronRegistry(db_path=db_path)

    spec = NeuronSpec(
        name="neurona-test-governance",
        mission="Probar el ciclo de gobernanza de neuronas con reglas duplicadas.",
        domain="system_governance",
        rules=[
            "Regla A",
            "Regla B",
            "Regla A",
            "",
            "Regla C",
            "Regla B",
        ],
        status="candidate",
        created_by="test",
    )

    registry.register(spec)
    stored = registry.get_neuron("neurona-test-governance")
    assert stored is not None
    assert stored["rules"] == ["Regla A", "Regla B", "Regla C"]
    assert stored["status"] == "candidate"

    updated = registry.update_status("neurona-test-governance", "experimental")
    assert updated["status"] == "experimental"


def test_decision_gate_approves_only_to_experimental(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    decisions_path = tmp_path / "primary_neuron_decisions.json"

    registry = NeuronRegistry(db_path=db_path)
    spec = NeuronSpec(
        name="neurona-test-decision",
        mission="Probar aprobación humana controlada.",
        domain="system_governance",
        rules=["Regla de prueba"],
        status="candidate",
        created_by="test",
    )
    registry.register(spec)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/decide_primary_neuron.py",
            "approve",
            "neurona-test-decision",
            "--db-path",
            str(db_path),
            "--decisions-path",
            str(decisions_path),
            "--reason",
            "Test approval",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_env(),
    )

    assert result.returncode == 0, result.stderr or result.stdout

    updated = registry.get_neuron("neurona-test-decision")
    assert updated is not None
    assert updated["status"] == "experimental"

    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    assert decisions[-1]["decision"] == "approve"
    assert decisions[-1]["next_status"] == "experimental"
    assert decisions[-1]["policy"] == "human_decision_required_no_auto_stable"


def test_decision_gate_never_exposes_stable_action() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/decide_primary_neuron.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
        env=_env(),
    )
    assert result.returncode == 0
    assert "approve" in result.stdout
    assert "reject" in result.stdout
    assert "request-changes" in result.stdout
    assert " stable" not in result.stdout.lower()

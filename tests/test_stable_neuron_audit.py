from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from triade.core.neuron_creator import NeuronSpec
from triade.core.neuron_registry import NeuronRegistry
from triade.core.stable_neuron_audit import audit_stable_neurons, apply_stable_neuron_audit
from triade.core.neuron_activity_store import NeuronActivityStore


def _insert_run(db_path: Path, run_id: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO runs (run_id, source, user_input, status)
            VALUES (?, 'test', 'stable audit', 'ok')
            """,
            (run_id,),
        )


def _insert_activity(
    db_path: Path,
    *,
    run_id: str,
    neuron_id: int,
    name: str,
    diagnosis_count: int,
    test_plan_count: int,
) -> None:
    _insert_run(db_path, run_id)
    store = NeuronActivityStore(db_path=db_path)
    store.store_activity(
        run_id=run_id,
        activity={
            "active": True,
            "activations": [
                {
                    "neuron_id": neuron_id,
                    "name": name,
                    "domain": "system_governance",
                    "status": "stable",
                    "diagnosis_count": diagnosis_count,
                    "test_plan_count": test_plan_count,
                    "policy": "worker_task",
                    "output": {
                        "diagnosis": ["d"] * diagnosis_count,
                        "test_plan": ["t"] * test_plan_count,
                    },
                }
            ],
        },
    )


def test_stable_neuron_audit_reports_and_apply(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    registry = NeuronRegistry(db_path=db_path)
    good_id = registry.register(NeuronSpec(
        name="neurona-estable-fuerte",
        mission="Auditar memoria y estabilidad con evidencia repetida.",
        domain="system_governance",
        rules=["r1", "r2", "r3", "r4", "r5"],
        status="stable",
        created_by="test",
    ))
    weak_id = registry.register(NeuronSpec(
        name="neurona-estable-debil",
        mission="Auditar memoria pero sin evidencia suficiente.",
        domain="system_governance",
        rules=["r1", "r2", "r3", "r4", "r5"],
        status="stable",
        created_by="test",
    ))

    for idx in range(5):
        _insert_activity(
            db_path,
            run_id=f"run-good-{idx}",
            neuron_id=good_id,
            name="neurona-estable-fuerte",
            diagnosis_count=1,
            test_plan_count=1,
        )
    _insert_activity(
        db_path,
        run_id="run-weak-0",
        neuron_id=weak_id,
        name="neurona-estable-debil",
        diagnosis_count=0,
        test_plan_count=0,
    )

    before_identity_core = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM identity_core").fetchone()[0]
    report = audit_stable_neurons(db_path=db_path, runs_dir=runs_dir, limit=20)

    assert report["status"] == "ok"
    assert report["mode"] == "stable_neuron_audit"
    assert report["total_stable_neurons"] == 2
    assert report["stable_with_enough_evidence"] == 1
    assert report["stable_needs_review"] == 1

    good = next(item for item in report["neurons"] if item["name"] == "neurona-estable-fuerte")
    weak = next(item for item in report["neurons"] if item["name"] == "neurona-estable-debil")
    assert good["recommended_action"] == "keep_stable"
    assert weak["recommended_action"] in {"mark_needs_review", "demote_to_experimental"}
    assert weak["apply_allowed"] is False
    assert report["policy"]["read_only_by_default"] is True

    applied = apply_stable_neuron_audit(db_path=db_path, runs_dir=runs_dir, limit=20, apply=True)
    assert applied["applied"] is True
    assert applied["applied_count"] == 1
    assert applied["policy"]["identity_core_modified"] is False

    good_after = registry.get_neuron("neurona-estable-fuerte")
    weak_after = registry.get_neuron("neurona-estable-debil")
    assert good_after["status"] == "stable"
    assert weak_after["status"] in {"needs_review", "experimental"}

    after_identity_core = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM identity_core").fetchone()[0]
    assert before_identity_core == after_identity_core


def test_stable_neuron_audit_cli(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    registry = NeuronRegistry(db_path=db_path)
    neuron_id = registry.register(NeuronSpec(
        name="neurona-estable-cli",
        mission="Auditar estado estable por CLI.",
        domain="system_governance",
        rules=["r1", "r2", "r3", "r4", "r5"],
        status="stable",
        created_by="test",
    ))
    _insert_activity(
        db_path,
        run_id="run-cli-0",
        neuron_id=neuron_id,
        name="neurona-estable-cli",
        diagnosis_count=0,
        test_plan_count=0,
    )

    result = subprocess.run(
        [
            sys.executable,
            "triade_digimon.py",
            "neuron",
            "audit-stable",
            "--db",
            str(db_path),
            "--runs-dir",
            str(runs_dir),
            "--apply",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["mode"] == "stable_neuron_audit"
    assert payload["applied"] is True
    assert payload["applied_count"] == 1

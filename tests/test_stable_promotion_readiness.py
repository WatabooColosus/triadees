from __future__ import annotations

import json
from pathlib import Path

from triade.core.stable_promotion_readiness import evaluate_stable_readiness


def write_activity(run_path: Path, activation_count_marker: int = 1) -> None:
    run_path.mkdir(parents=True, exist_ok=True)
    activity = {
        "active": True,
        "count": 1,
        "activations": [
            {
                "neuron_id": 16,
                "name": "neurona-verifica-estado-actual",
                "status": "experimental",
                "domain": "federation_android_edge",
                "match": {"active": True, "reasons": [f"test-{activation_count_marker}"]},
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


def test_stable_readiness_blocks_when_evidence_is_insufficient(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    write_activity(runs_dir / "run-test-001")

    report = evaluate_stable_readiness(runs_dir=runs_dir, limit=10)

    assert report["mode"] == "stable_promotion_readiness"
    assert report["summary"]["policy"] == "readiness_only_no_auto_stable"
    assert report["summary"]["ready_for_stable_review"] == 0
    assert report["summary"]["not_ready"] == 1

    neuron = report["neurons"][0]
    assert neuron["name"] == "neurona-verifica-estado-actual"
    assert neuron["ready_for_stable_review"] is False
    assert neuron["required_human_decision"] is True
    assert any("activation_count" in blocker for blocker in neuron["blockers"])
    assert any("diagnosis_count" in blocker for blocker in neuron["blockers"])


def test_stable_readiness_ready_only_after_thresholds(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"

    for i in range(5):
        write_activity(runs_dir / f"run-test-{i:03d}", activation_count_marker=i)

    report = evaluate_stable_readiness(runs_dir=runs_dir, limit=10)

    assert report["summary"]["ready_for_stable_review"] == 1
    assert report["summary"]["not_ready"] == 0

    neuron = report["neurons"][0]
    assert neuron["activation_count"] == 5
    assert neuron["diagnosis_count"] == 10
    assert neuron["test_plan_count"] == 5
    assert neuron["ready_for_stable_review"] is True
    assert neuron["blockers"] == []
    assert neuron["policy"] == "readiness_only_no_auto_stable"


def test_stable_readiness_can_be_tuned_with_thresholds(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    write_activity(runs_dir / "run-test-001")

    report = evaluate_stable_readiness(
        runs_dir=runs_dir,
        limit=10,
        thresholds={
            "min_activations": 1,
            "min_diagnosis": 2,
            "min_test_plan": 1,
        },
    )

    neuron = report["neurons"][0]
    assert neuron["ready_for_stable_review"] is True
    assert neuron["blockers"] == []
    assert report["summary"]["thresholds"]["min_activations"] == 1


def test_stable_readiness_does_not_claim_stable_promotion(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"

    for i in range(5):
        write_activity(runs_dir / f"run-test-{i:03d}", activation_count_marker=i)

    report = evaluate_stable_readiness(runs_dir=runs_dir, limit=10)
    payload = json.dumps(report, ensure_ascii=False).lower()

    assert "readiness_only_no_auto_stable" in payload
    assert "ready_for_stable_review" in payload
    assert "promoted" not in payload
    assert "next_status" not in payload
    assert '"status": "stable"' not in payload

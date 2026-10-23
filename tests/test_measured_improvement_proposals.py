"""Measured regressions are the only supported source of autonomous proposals.

All SQLite writes in this test are synthetic, isolated in tmp_path.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from triade.neuron_factory import (
    NeuronSpecification,
    NeuronSpecificationStore,
    ResourceBudget,
)
from triade.self_improvement.failure_learning import FailureLearningLoop
from triade.self_improvement.measured_proposals import propose_from_measured_failures

CAPABILITY = "triade_vitality"


def register_spec(
    db: Path, *, capability: str = CAPABILITY, neuron_id: str = "n1"
) -> None:
    store = NeuronSpecificationStore(db)
    spec = NeuronSpecification(
        neuron_id=neuron_id,
        name="synthetic neuron",
        mission="medir la vitalidad del sistema en pruebas",
        domain="system",
        version="1.0.0",
        owner="test",
        component="triade.neurons.measured_test",
        input_contract={"type": "object"},
        output_contract={"type": "object"},
        provides_capabilities=(capability,),
        resource_budget=ResourceBudget(512, 300, 10),
    )
    store.register(spec)
    store.transition(neuron_id, "1.0.0", "specified")


def record_real_shaped_regression(db: Path, report_id: str) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS regression_reports ("
            "report_id TEXT, candidate_id TEXT, capability TEXT,"
            "decision TEXT, findings_json TEXT)"
        )
        conn.execute(
            "INSERT INTO regression_reports VALUES (?,?,?,?,?)",
            (
                report_id,
                "candidate-" + report_id,
                CAPABILITY,
                "fail",
                json.dumps(
                    [
                        {
                            "metric_id": "coherence",
                            "severity": "high",
                            "baseline_score": 0.9,
                            "candidate_score": 0.7,
                            "absolute_delta": -0.2,
                            "status": "fail",
                            "reason": "measured regression in synthetic gate",
                        }
                    ]
                ),
            ),
        )


def proposals(db: Path) -> list[dict]:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                "SELECT proposal_id, signal_id, status, payload_json "
                "FROM improvement_proposals ORDER BY proposal_id"
            )
        ]


def test_five_verified_failures_and_spec_produce_one_bounded_proposal(tmp_path: Path):
    db = tmp_path / "real_shaped.db"
    learner = FailureLearningLoop(db)
    register_spec(db)
    for index in range(1, 5):
        record_real_shaped_regression(db, f"r{index}")
        outcome = learner.harvest(limit=20)
        assert outcome["proposal_readiness"]["proposals_created"] == 0
        assert proposals(db) == []

    record_real_shaped_regression(db, "r5")
    outcome = learner.harvest(limit=20)
    assert outcome["proposal_readiness"]["proposals_created"] == 1
    rows = proposals(db)
    assert len(rows) == 1
    assert rows[0]["status"] == "open"
    payload = json.loads(rows[0]["payload_json"])
    assert payload["neuron_id"] == "n1"
    assert payload["version"] == "1.0.0"
    assert payload["requires_human_approval"] is True
    assert payload["requested_capability"] == CAPABILITY
    assert payload["hypothesis"]
    assert learner.harvest(limit=20)["proposal_readiness"]["proposals_created"] == 0
    assert len(proposals(db)) == 1


def test_unregistered_or_ambiguous_destination_blocks_proposals(tmp_path: Path):
    db = tmp_path / "real_shaped.db"
    learner = FailureLearningLoop(db)
    for index in range(1, 6):
        record_real_shaped_regression(db, f"r{index}")
    first = learner.harvest(limit=20)
    assert first["proposal_readiness"]["proposals_created"] == 0
    assert any(
        i["reason"] == "no_unique_authorized_neuron_specification"
        for i in first["proposal_readiness"]["skipped"]
    )
    register_spec(db, neuron_id="n1")
    register_spec(db, neuron_id="n2")
    second = learner.harvest(limit=20)
    assert second["proposal_readiness"]["proposals_created"] == 0
    assert proposals(db) == []


def test_signal_without_regression_evidence_never_makes_proposal(tmp_path: Path):
    db = tmp_path / "real_shaped.db"
    FailureLearningLoop(db)  # Explicitly initialise isolated SQLite schema.
    register_spec(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO improvement_signals VALUES (?,?,?,?,?,?,?)",
            (
                "manual-signal",
                CAPABILITY,
                "coherence",
                "open",
                1.0,
                json.dumps(
                    {
                        "capability_id": CAPABILITY,
                        "metric_id": "coherence",
                        "confidence": 0.99,
                        "risk_level": "low",
                        "source_ref": "manual",
                    }
                ),
                1.0,
            ),
        )
    result = propose_from_measured_failures(db)
    assert result["proposals_created"] == 0
    assert result["skipped"][0]["reason"] == "signal_has_no_verified_regression_origin"
    assert proposals(db) == []

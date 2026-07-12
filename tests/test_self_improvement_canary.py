import json
import sqlite3
from pathlib import Path

import pytest

from triade.neuron_factory import NeuronSpecification, NeuronSpecificationStore, ResourceBudget
from triade.self_improvement.canary import CanaryMonitor


def prepare_promoted_candidate(db_path: Path) -> str:
    store = NeuronSpecificationStore(db_path)
    specification = NeuronSpecification(
        neuron_id="neuron.canary",
        name="Canary Neuron",
        mission="validar promoción limitada",
        domain="quality",
        version="1.0.0",
        owner="central",
        component="triade.neurons.canary",
        input_contract={"type": "object"},
        output_contract={"type": "object"},
        provides_capabilities=("canary_quality",),
        resource_budget=ResourceBudget(256, 60, 16),
    )
    store.register(specification)
    for state in ("specified", "training", "evaluated", "promoted"):
        store.transition(specification.neuron_id, specification.version, state)

    candidate_id = "candidate-canary"
    manifest = {
        "candidate_id": candidate_id,
        "neuron_id": specification.neuron_id,
        "version": specification.version,
        "sandbox_id": "sandbox-canary",
        "specification_sha256": "a" * 64,
        "status": "promoted",
    }
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS neuron_candidates (
                candidate_id TEXT PRIMARY KEY,
                neuron_id TEXT NOT NULL,
                version TEXT NOT NULL,
                sandbox_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                manifest_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        conn.execute(
            """INSERT INTO neuron_candidates
            (candidate_id, neuron_id, version, sandbox_id, status, manifest_json)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                candidate_id,
                specification.neuron_id,
                specification.version,
                manifest["sandbox_id"],
                manifest["status"],
                json.dumps(manifest, sort_keys=True),
            ),
        )
    return candidate_id


def test_canary_requires_promoted_candidate(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    monitor = CanaryMonitor(db_path)

    with pytest.raises(KeyError, match="candidato no registrado"):
        monitor.start("missing", baseline_score=0.8)


def test_canary_graduates_after_stable_window(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    candidate_id = prepare_promoted_candidate(db_path)
    monitor = CanaryMonitor(db_path)
    canary = monitor.start(
        candidate_id,
        baseline_score=0.8,
        tolerance=0.05,
        traffic_percent=10,
        min_observations=2,
        max_observations=3,
    )

    assert monitor.observe(canary["canary_id"], score=0.81)["status"] == "running"
    assert monitor.observe(canary["canary_id"], score=0.79)["status"] == "running"
    result = monitor.observe(canary["canary_id"], score=0.80)

    assert result["status"] == "graduated"
    assert result["observation_count"] == 3
    assert result["rollback"] is None


def test_canary_rolls_back_after_confirmed_degradation(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    candidate_id = prepare_promoted_candidate(db_path)
    monitor = CanaryMonitor(db_path)
    canary = monitor.start(
        candidate_id,
        baseline_score=0.8,
        tolerance=0.02,
        min_observations=2,
        max_observations=5,
    )

    monitor.observe(canary["canary_id"], score=0.70)
    result = monitor.observe(canary["canary_id"], score=0.72)

    assert result["status"] == "rolled_back"
    assert result["rollback"]["status"] == "rolled_back"
    assert monitor.lifecycle.candidates.get(candidate_id)["status"] == "rolled_back"
    assert monitor.lifecycle.specifications.get("neuron.canary", "1.0.0")["state"] == "quarantined"


def test_finished_canary_rejects_more_observations(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    candidate_id = prepare_promoted_candidate(db_path)
    monitor = CanaryMonitor(db_path)
    canary = monitor.start(candidate_id, baseline_score=0.8, min_observations=1, max_observations=1)
    monitor.observe(canary["canary_id"], score=0.8)

    with pytest.raises(ValueError, match="ya terminó"):
        monitor.observe(canary["canary_id"], score=0.8)


def test_canary_traffic_is_hard_limited(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    candidate_id = prepare_promoted_candidate(db_path)
    monitor = CanaryMonitor(db_path)

    with pytest.raises(ValueError, match="traffic_percent"):
        monitor.start(candidate_id, baseline_score=0.8, traffic_percent=50)

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from triade.federation import FederatedEvidenceGate, FederatedNodeIdentity, FederatedNodeRegistry


def evaluation(evaluation_id: str, score: float) -> dict:
    return {
        "evaluation_id": evaluation_id,
        "suite_id": "remote-quality-suite",
        "suite_version": "1.0.0",
        "subject_id": evaluation_id,
        "results": [
            {
                "case_id": "quality",
                "score": score,
                "passed": score >= 0.8,
                "actual": score,
                "expected": 1.0,
                "details": {},
            }
        ],
        "aggregate_score": score,
        "created_at": "2026-07-12T00:00:00Z",
        "metadata": {},
    }


def evidence(baseline_score: float, candidate_score: float) -> dict:
    return {
        "baseline": evaluation("baseline", baseline_score),
        "candidate": evaluation("candidate", candidate_score),
        "policies": [
            {
                "metric_id": "quality",
                "severity": "high",
                "max_absolute_drop": 0.0,
                "max_relative_drop": 0.0,
                "required": True,
            }
        ],
    }


def prepare(db_path: Path, *, trust_score: float = 0.8) -> None:
    registry = FederatedNodeRegistry(db_path)
    registry.register(
        FederatedNodeIdentity(
            node_id="remote-01",
            display_name="Remote 01",
            endpoint="https://remote.example.test",
            public_key="REMOTE-PUBLIC-KEY",
            capabilities=("research_verified",),
            permissions=("submit_work", "return_evidence"),
        )
    )
    registry.transition(
        "remote-01",
        "trusted",
        actor="human-operator",
        reason="clave verificada",
        trust_score=trust_score,
    )


def insert_job(db_path: Path, job_id: str, payload: dict, *, status: str = "completed") -> None:
    FederatedEvidenceGate(db_path)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    evidence_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    result = {"evidence": payload, "evidence_sha256": evidence_sha}
    stored = {"request": {}, "result": result}
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO federated_jobs
            (job_id, remote_node_id, capability, status, request_sha256,
             result_sha256, payload_json, created_at, updated_at)
            VALUES (?, 'remote-01', 'research_verified', ?, 'request-sha',
                    'result-sha', ?, 1.0, 1.0)""",
            (job_id, status, json.dumps(stored, sort_keys=True)),
        )


def test_passed_remote_evidence_increases_trust(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    prepare(db_path, trust_score=0.8)
    insert_job(db_path, "job-pass", evidence(0.7, 0.9))
    gate = FederatedEvidenceGate(db_path)

    result = gate.assess("job-pass")

    assert result["decision"] == "pass"
    assert result["trust_before"] == pytest.approx(0.8)
    assert result["trust_after"] == pytest.approx(0.83)
    assert result["node_state"] == "trusted"
    assert result["regression_report"]["metadata"]["source"] == "federated"


def test_failed_remote_evidence_quarantines_node(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    prepare(db_path, trust_score=0.8)
    insert_job(db_path, "job-fail", evidence(0.9, 0.6))
    gate = FederatedEvidenceGate(db_path)

    result = gate.assess("job-fail")

    assert result["decision"] == "fail"
    assert result["trust_after"] == pytest.approx(0.65)
    assert result["node_state"] == "quarantined"
    assert FederatedNodeRegistry(db_path).authorize(
        "remote-01", capability="research_verified", permission="submit_work"
    ) is False


def test_assessment_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    prepare(db_path)
    insert_job(db_path, "job-repeat", evidence(0.7, 0.9))
    gate = FederatedEvidenceGate(db_path)
    first = gate.assess("job-repeat")
    second = gate.assess("job-repeat")

    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert second["trust_after"] == first["trust_after"]


def test_tampered_evidence_is_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    prepare(db_path)
    payload = evidence(0.7, 0.9)
    insert_job(db_path, "job-tampered", payload)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT payload_json FROM federated_jobs WHERE job_id = 'job-tampered'"
        ).fetchone()
        stored = json.loads(row[0])
        stored["result"]["evidence"]["candidate"]["aggregate_score"] = 0.1
        conn.execute(
            "UPDATE federated_jobs SET payload_json = ? WHERE job_id = 'job-tampered'",
            (json.dumps(stored, sort_keys=True),),
        )

    with pytest.raises(ValueError, match="huella"):
        FederatedEvidenceGate(db_path).assess("job-tampered")


def test_only_completed_jobs_can_be_assessed(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    prepare(db_path)
    insert_job(db_path, "job-failed", evidence(0.7, 0.9), status="failed")

    with pytest.raises(ValueError, match="completed"):
        FederatedEvidenceGate(db_path).assess("job-failed")

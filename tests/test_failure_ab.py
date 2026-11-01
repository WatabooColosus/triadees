"""Un fallo real no se convierte en mejora por repetir una prueba."""

import json
import sqlite3

import pytest

from triade.self_improvement.failure_ab import (
    CandidateVariant,
    FailureABGate,
    FailureCase,
)


def _failed_report(path, decision="fail"):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE regression_reports (report_id TEXT PRIMARY KEY,"
            "capability TEXT, decision TEXT, findings_json TEXT)"
        )
        findings = [
            {
                "metric_id": "worker_correctness",
                "status": "fail",
                "baseline_score": 0.90,
                "candidate_score": 0.60,
            }
        ]
        conn.execute(
            "INSERT INTO regression_reports VALUES (?,?,?,?)",
            ("reg-real-1", "worker_failure", decision, json.dumps(findings)),
        )


def _cases():
    cases = []
    for split, count in (("train", 4), ("holdout", 5), ("negative", 2)):
        for i in range(count):
            cid = f"{split}-{i}"
            cases.append(
                FailureCase(
                    case_id=cid,
                    split=split,
                    inputs={"case_id": cid, "split": split},
                    expected=1,
                    evidence_ref=f"independent-report:{cid}",
                    safety_critical=(split == "negative"),
                )
            )
    return cases


def _baseline(payload):
    return 1 if payload["split"] == "negative" else 0


def _correct(payload):
    return 1


def _bad(payload):
    return 0


def _oracle(case):
    return case.evidence_ref == "independent-report:" + case.case_id


def _run(db, variants, *, cases=None, oracle=_oracle):
    return FailureABGate(db).run(
        report_id="reg-real-1",
        metric_id="worker_correctness",
        cases=cases if cases is not None else _cases(),
        baseline=_baseline,
        variants=variants,
        independent_oracle=oracle,
    )


def test_ab_variants_select_training_winner_then_independent_holdout(tmp_path):
    db = tmp_path / "triade.sqlite3"
    _failed_report(db)
    loser_evaluations = []

    def loser(payload):
        loser_evaluations.append(payload["split"])
        return 0

    variants = [
        CandidateVariant("B1_bad", loser),
        CandidateVariant("B2_better", _correct),
    ]
    result = _run(db, variants)
    assert result["winner"] == "B2_better"
    assert result["train_baseline"] == 0
    assert result["holdout_baseline"] == 0
    assert result["holdout_candidate"] == 1
    assert result["negative_baseline"] == result["negative_candidate"] == 1
    assert result["eligible_for_canary"] is True
    assert result["status"] == "eligible_for_governed_review"
    assert result["stable_memory_written"] is False
    assert all(split == "train" for split in loser_evaluations)


def test_negative_control_blocks_candidate_despite_holdout_improvement(tmp_path):
    db = tmp_path / "triade.sqlite3"
    _failed_report(db)

    def unsafe(payload):
        return 0 if payload["split"] == "negative" else 1

    result = _run(db, [CandidateVariant("B1", unsafe)])
    assert result["holdout_candidate"] == 1
    assert result["critical_controls_passed"] is False
    assert result["eligible_for_canary"] is False
    assert result["status"] == "regressed_or_no_transfer"


def test_no_train_improvement_does_not_expose_holdout(tmp_path):
    db = tmp_path / "triade.sqlite3"
    _failed_report(db)
    touched = []

    def bad(payload):
        touched.append(payload["split"])
        return 0

    result = _run(db, [CandidateVariant("B1", bad)])
    assert result["status"] == "insufficient_improvement"
    assert result["holdout_executed"] is False
    assert all(split == "train" for split in touched)


def test_failure_gate_refuses_unverified_or_duplicate_data(tmp_path):
    db = tmp_path / "triade.sqlite3"
    _failed_report(db)
    with pytest.raises(ValueError, match="case_origin_not_independently_verified"):
        _run(db, [CandidateVariant("B1", _correct)], oracle=lambda _: False)
    cases = _cases()
    cases[-1] = FailureCase(
        case_id=cases[0].case_id,
        split="negative",
        inputs={},
        expected=1,
        evidence_ref="new",
        safety_critical=True,
    )
    with pytest.raises(ValueError, match="duplicated_or_unattested_case"):
        _run(db, [CandidateVariant("B1", _correct)], cases=cases)
    with pytest.raises(ValueError, match="independent_oracle_required"):
        _run(db, [CandidateVariant("B1", _correct)], oracle=None)


def test_report_must_be_real_and_failed(tmp_path):
    db = tmp_path / "triade.sqlite3"
    _failed_report(db, decision="pass")
    with pytest.raises(ValueError, match="verified_failed_regression_required"):
        _run(db, [CandidateVariant("B1", _correct)])


def test_same_frozen_suite_cannot_repeat_holdout(tmp_path):
    db = tmp_path / "triade.sqlite3"
    _failed_report(db)
    first = _run(db, [CandidateVariant("B1", _correct)])

    def forbidden(_):
        raise AssertionError("no se debe reabrir el holdout")

    second = _run(db, [CandidateVariant("B1", forbidden)])
    assert second == first
    with sqlite3.connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM failure_ab_experiments").fetchone()[0]
    assert count == 1


def test_distinct_independent_sources_are_required(tmp_path):
    db = tmp_path / "triade.sqlite3"
    _failed_report(db)
    cases = _cases()
    previous = cases[-1]
    cases[-1] = FailureCase(
        previous.case_id,
        previous.split,
        previous.inputs,
        previous.expected,
        cases[0].evidence_ref,
        previous.safety_critical,
    )
    with pytest.raises(ValueError, match="duplicated_or_unattested_case"):
        _run(db, [CandidateVariant("B1", _correct)], cases=cases)


def test_disallows_version_collision_and_unbounded_variants(tmp_path):
    db = tmp_path / "triade.sqlite3"
    _failed_report(db)
    with pytest.raises(ValueError, match="invalid_candidate_versions"):
        _run(db, [CandidateVariant("B", _correct), CandidateVariant("B", _bad)])
    with pytest.raises(ValueError, match="invalid_variant_budget"):
        _run(db, [CandidateVariant(f"B{i}", _correct) for i in range(5)])

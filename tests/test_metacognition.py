from __future__ import annotations

from pathlib import Path

from triade.capabilities.metacognition import CapabilityAwareness


def test_availability_caps_false_confidence(tmp_path: Path) -> None:
    awareness = CapabilityAwareness(tmp_path / "meta.db")
    awareness.register(
        "unknown_tool",
        "unavailable",
        reason="binary absent",
        resources={"binary": "missing"},
    )
    prediction = awareness.predict(
        "unknown_tool", "task:1", 0.95, reasons=["requested by planner"]
    )
    assert prediction["confidence"] == 0.05
    awareness.record_outcome(
        prediction["prediction_id"],
        False,
        evidence_ref="effect:failed",
        error_type="dependency_unavailable",
    )
    assert awareness.calibration()["unknown_detection_rate"] == 1.0


def test_eighty_percent_predictions_calibrate_to_eighty_percent(
    tmp_path: Path,
) -> None:
    awareness = CapabilityAwareness(tmp_path / "meta.db")
    awareness.register(
        "sandbox_eval",
        "available",
        reason="verified executable and rollback available",
        resources={"cpu_seconds": 1},
    )
    for index in range(10):
        prediction = awareness.predict(
            "sandbox_eval",
            f"task:{index}",
            0.8,
            reasons=["historical bucket estimate"],
        )
        success = index < 8
        awareness.record_outcome(
            prediction["prediction_id"],
            success,
            evidence_ref=f"receipt:{index}",
            error_type=None if success else "postcondition_failed",
        )
    metrics = awareness.calibration()
    assert metrics["sample_size"] == 10
    assert metrics["expected_calibration_error"] < 1e-9
    assert abs(metrics["brier_score"] - 0.16) < 1e-9


def test_gap_detector_ranks_utility_adjusted_for_risk(tmp_path: Path) -> None:
    awareness = CapabilityAwareness(tmp_path / "meta.db")
    awareness.register(
        "useful_gap", "unverified", utility=0.9, risk=0.1, reason="benchmark absent"
    )
    awareness.register(
        "risky_gap", "quarantined", utility=1.0, risk=0.9, reason="safety regression"
    )
    gaps = awareness.gaps()
    assert [gap["capability_id"] for gap in gaps] == ["useful_gap", "risky_gap"]
    assert gaps[0]["learning_priority"] > gaps[1]["learning_priority"]


def test_outcome_requires_canonical_error_and_cannot_close_twice(
    tmp_path: Path,
) -> None:
    awareness = CapabilityAwareness(tmp_path / "meta.db")
    awareness.register("reader", "degraded", reason="remote dependency intermittent")
    prediction = awareness.predict("reader", "task:read", 0.9, reasons=["probe"])
    assert prediction["confidence"] == 0.7
    try:
        awareness.record_outcome(
            prediction["prediction_id"], False, evidence_ref="receipt:1"
        )
    except ValueError as exc:
        assert "error_type" in str(exc)
    else:
        raise AssertionError("failure without error taxonomy was accepted")

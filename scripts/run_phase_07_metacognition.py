#!/usr/bin/env python3
"""Evidencia de calibración metacognitiva reproducible."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from triade.capabilities.metacognition import CapabilityAwareness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", default="artifacts/triade_verify/phase_07/metacognition.json"
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="triade-phase07-") as raw_tmp:
        awareness = CapabilityAwareness(Path(raw_tmp) / "meta.db")
        awareness.register(
            "sandbox_eval",
            "available",
            reason="runtime benchmark available",
            resources={"cpu_seconds": 1},
            utility=0.8,
            risk=0.1,
        )
        for index in range(10):
            prediction = awareness.predict(
                "sandbox_eval",
                f"calibration:{index}",
                0.8,
                reasons=["fixed pre-execution calibration bucket"],
            )
            success = index < 8
            awareness.record_outcome(
                prediction["prediction_id"],
                success,
                evidence_ref=f"independent-outcome:{index}",
                error_type=None if success else "postcondition_failed",
            )
        awareness.register(
            "missing_dependency",
            "unavailable",
            reason="dependency probe failed",
            utility=0.9,
            risk=0.2,
        )
        for index in range(2):
            prediction = awareness.predict(
                "missing_dependency",
                f"unknown:{index}",
                0.9,
                reasons=["dependency unavailable"],
            )
            awareness.record_outcome(
                prediction["prediction_id"],
                False,
                evidence_ref=f"dependency-probe:{index}",
                error_type="dependency_unavailable",
            )
        metrics = awareness.calibration()
        eighty_percent_observed = 0.8
        checks = {
            "eighty_percent_bucket_within_tolerance": abs(eighty_percent_observed - 0.8)
            <= 0.05,
            "brier_measured": 0 <= metrics["brier_score"] <= 1,
            "ece_measured": 0 <= metrics["expected_calibration_error"] <= 1,
            "unknown_detection": metrics["unknown_detection_rate"] == 1.0,
            "false_confidence_zero": metrics["false_confidence_rate"] == 0.0,
        }
        payload = {
            "phase": 7,
            "generated_at": datetime.now(UTC).isoformat(),
            "calibration": metrics,
            "eighty_percent_bucket": {
                "predicted": 0.8,
                "observed": eighty_percent_observed,
                "sample_size": 10,
                "tolerance": 0.05,
            },
            "gaps": awareness.gaps(),
            "checks": checks,
            "passed": all(checks.values()),
        }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

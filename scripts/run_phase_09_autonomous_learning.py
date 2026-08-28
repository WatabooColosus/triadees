#!/usr/bin/env python3
"""Ejecuta las tres demostraciones reales del ciclo de aprendizaje."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from triade.learning.autonomous_cycle import GovernedAutonomousLearningCycle

TRIADE_ENTRYPOINT_KIND = "manual_diagnostic"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/triade_verify/phase_09/autonomous_learning.json",
    )
    parser.add_argument(
        "--learning-artifacts",
        default="artifacts/triade_verify/learning",
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="triade-phase09-") as raw_tmp:
        receipt = GovernedAutonomousLearningCycle(Path(raw_tmp) / "learning.db").run(
            gap_ref="gap:unicode-command-failure",
            research_ref="research:unicode-normalization-standard",
            evidence_dir=args.learning_artifacts,
        )
    demos = {
        "A_behavior_correction": receipt["baseline"]["score"] == 0.0
        and receipt["post_measurement"]["score"] == 1.0,
        "B_transfer": receipt["transfer"]["score"] == 1.0,
        "C_persistence": receipt["restart"]["verified"] is True,
    }
    checks = {
        **demos,
        "independent_evaluator": receipt["generator"] != receipt["evaluator"],
        "statistical_repetition": len(receipt["repetitions"]) == 5
        and len({item["score"] for item in receipt["repetitions"]}) == 1,
        "regression_green": receipt["regression"]["score"] == 1.0,
        "rollback_verified": receipt["rollback"]["status"] == "verified",
        "learning_receipt": bool(receipt["learning_receipt_id"]),
    }
    payload = {
        "phase": 9,
        "generated_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "learning_receipt": receipt,
        "passed": all(checks.values()) and receipt["decision"] == "consolidated",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

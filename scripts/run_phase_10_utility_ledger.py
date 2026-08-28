#!/usr/bin/env python3
"""Genera evidencia runtime reproducible de la Fase 10."""

import json
import tempfile
from pathlib import Path

from pydantic import ValidationError

from triade.runtime.utility_ledger import UtilityLedger, UtilityReceipt

TRIADE_ENTRYPOINT_KIND = "manual_diagnostic"


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        ledger = UtilityLedger(Path(directory) / "triade.db")
        base = {
            "goal": "prove restore utility",
            "baseline": {"recoverable": False},
            "quality_score": 1.0,
            "human_intervention": 0.0,
            "time_cost": 1.0,
            "cpu_cost": 0.1,
            "gpu_cost": 0.0,
            "memory_cost": 1.0,
            "storage_cost": 2.0,
            "network_cost": 0.0,
            "risk": "low",
            "regressions": [],
        }
        pulse_blocked = False
        try:
            UtilityReceipt.model_validate(
                {
                    **base,
                    "classification": "utility",
                    "outcome": {"kind": "pulse"},
                    "improvement": 1.0,
                    "verified": True,
                    "evidence_ref": "artifact:pulse",
                    "effect_receipt_ref": "effect:pulse",
                }
            )
        except ValidationError:
            pulse_blocked = True
        valid = UtilityReceipt.model_validate(
            {
                **base,
                "classification": "utility",
                "outcome": {"kind": "verified_backup", "restored": True},
                "improvement": 1.0,
                "verified": True,
                "evidence_ref": "artifact:restore-report",
                "effect_receipt_ref": "effect:backup-restored",
            }
        )
        ledger.record(valid)
        report = {
            "phase": 10,
            "pulse_utility_blocked": pulse_blocked,
            "backup_utility_recorded": True,
            "receipt": valid.model_dump(mode="json"),
            "summary": ledger.summary(),
        }
    report["passed"] = all(
        [report["pulse_utility_blocked"], report["backup_utility_recorded"]]
    )
    output = Path("artifacts/triade_verify/phase_10/utility_ledger.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

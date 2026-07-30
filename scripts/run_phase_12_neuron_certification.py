#!/usr/bin/env python3
"""Audita y pone en cuarentena neuronas stable sin certificación."""

import json
from pathlib import Path

from triade.neuron_factory.certification import NeuronCertifier


def main() -> int:
    db = Path("triade/memory/triade.db")
    certifier = NeuronCertifier(db)
    before = certifier.audit_stable()
    result = certifier.apply_quarantine("artifacts/triade_verify/phase_12/rollback")
    after = certifier.audit_stable()
    report = {"phase": 12, "before": before, "application": result, "after": after}
    report["passed"] = (
        before["stable_count"] == 13
        and result["applied_count"] == before["insufficient_count"]
        and after["insufficient_count"] == 0
    )
    output = Path("artifacts/triade_verify/phase_12/neuron_certification.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "before": before,
                "applied_count": result["applied_count"],
                "after": after,
                "passed": report["passed"],
            },
            indent=2,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

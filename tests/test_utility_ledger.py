from pathlib import Path

import pytest
from pydantic import ValidationError

from triade.runtime.utility_ledger import UtilityLedger, UtilityReceipt


def receipt(**overrides: object) -> UtilityReceipt:
    values: dict[str, object] = {
        "goal": "verify backup",
        "classification": "activity",
        "baseline": {"recoverable": False},
        "outcome": {"kind": "scan"},
        "improvement": 0.0,
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
        "verified": False,
    }
    values.update(overrides)
    return UtilityReceipt.model_validate(values)


@pytest.mark.parametrize("kind", ["pulse", "heartbeat", "maintenance"])
def test_telemetry_never_generates_utility(kind: str) -> None:
    with pytest.raises(ValidationError, match="cannot_claim_utility"):
        receipt(
            classification="utility",
            outcome={"kind": kind},
            improvement=1.0,
            verified=True,
            evidence_ref="artifact:pulse",
            effect_receipt_ref="effect:pulse",
        )


def test_scan_without_correction_has_no_improvement() -> None:
    item = receipt(outcome={"kind": "scan", "findings": 2})
    assert item.classification == "activity"
    assert item.improvement == 0.0


def test_completed_without_effect_cannot_generate_utility() -> None:
    with pytest.raises(ValidationError, match="effect_receipt"):
        receipt(
            classification="utility",
            outcome={"kind": "completed", "effect": None},
            improvement=1.0,
            verified=True,
            evidence_ref="artifact:output",
        )


def test_verified_backup_can_generate_operational_utility(tmp_path: Path) -> None:
    ledger = UtilityLedger(tmp_path / "triade.db")
    item = receipt(
        classification="utility",
        outcome={"kind": "verified_backup", "restored": True},
        improvement=1.0,
        verified=True,
        evidence_ref="artifact:restore-report",
        effect_receipt_ref="effect:backup-created-and-restored",
    )
    ledger.record(item)
    assert ledger.summary() == {
        "counts": {"utility": 1},
        "verified_improvement": 1.0,
    }

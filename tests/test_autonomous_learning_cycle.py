from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.learning.autonomous_cycle import (
    CommandInterpreter,
    GovernedAutonomousLearningCycle,
)


def test_learning_cycle_demonstrates_correction_transfer_and_restart(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "learning.db"
    receipt = GovernedAutonomousLearningCycle(db_path).run(
        gap_ref="gap:unicode-command-failure",
        research_ref="research:unicode-normalization",
        evidence_dir=tmp_path / "evidence",
    )
    assert receipt["baseline"]["score"] == 0.0
    assert receipt["post_measurement"]["score"] == 1.0
    assert receipt["improvement"] == 1.0
    assert receipt["transfer"]["score"] == 1.0
    assert receipt["regression"]["score"] == 1.0
    assert receipt["rollback"]["status"] == "verified"
    assert receipt["restart"]["verified"] is True
    assert receipt["decision"] == "consolidated"
    assert set(receipt["benchmark_separation"]["creation_inputs"]).isdisjoint(
        receipt["benchmark_separation"]["transfer_inputs"]
    )


def test_learning_receipt_is_persisted_and_active_after_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "learning.db"
    receipt = GovernedAutonomousLearningCycle(db_path).run(
        gap_ref="gap:1", research_ref="research:1", evidence_dir=tmp_path / "evidence"
    )
    assert Path(receipt["evidence_bundle"]).is_file()
    assert (
        CommandInterpreter(db_path).interpret("ｒｕｎｔｉｍｅ　ｄｏｃｔｏｒ")
        == "runtime doctor"
    )
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT decision FROM autonomous_learning_receipts WHERE learning_receipt_id = ?",
            (receipt["learning_receipt_id"],),
        ).fetchone()
    assert row == ("consolidated",)


def test_repetitions_are_stable_and_evaluator_is_independent(tmp_path: Path) -> None:
    receipt = GovernedAutonomousLearningCycle(tmp_path / "learning.db").run(
        gap_ref="gap:1", research_ref="research:1", evidence_dir=tmp_path / "evidence"
    )
    assert len(receipt["repetitions"]) == 5
    assert {item["score"] for item in receipt["repetitions"]} == {1.0}
    assert receipt["generator"] != receipt["evaluator"]

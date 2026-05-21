"""Tests de Core Alignment 1.7."""

from __future__ import annotations

from triade.core.alignment import CoreAlignment


def test_core_alignment_static_report() -> None:
    alignment = CoreAlignment()
    report = alignment.evaluate_static_core()

    assert report["status"] in {"partial", "operational", "strong"}
    assert report["score"] >= 0.7
    assert len(report["organs"]) == 5
    organs = {item["organ"] for item in report["organs"]}
    assert organs == {"central", "hypothalamus", "bodega", "crystal", "runner"}


def test_core_alignment_artifacts_report() -> None:
    alignment = CoreAlignment()
    report = alignment.evaluate_run_artifacts(
        [
            "input.json",
            "signals.json",
            "memory.json",
            "crystal.json",
            "plan.json",
            "safety.json",
            "output.json",
            "memory_diff.json",
            "report.json",
            "integrity.json",
            "CLOSED",
        ]
    )

    assert report["status"] == "strong"
    assert report["score"] == 1.0
    assert report["missing"] == []


def test_core_alignment_detects_missing_artifacts() -> None:
    alignment = CoreAlignment()
    report = alignment.evaluate_run_artifacts(["input.json", "signals.json"])

    assert report["status"] in {"weak", "partial"}
    assert report["score"] < 0.5
    assert "CLOSED" in report["missing"]

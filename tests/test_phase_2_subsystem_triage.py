from __future__ import annotations

import json
from pathlib import Path

from scripts.build_phase_2_subsystem_triage import REVIEWS

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/debt/debt-triage-20260803.json"
ARTIFACT = ROOT / "artifacts/evolution/subsystem_triage.json"

DECISIONS = {
    "activate_now",
    "complete_later",
    "merge_with_existing",
    "experimental_keep",
    "legacy_archive",
    "remove_from_productive_graph",
}
REQUIRED_FIELDS = {
    "id",
    "name",
    "group",
    "owner",
    "files",
    "tables",
    "mission",
    "producer",
    "consumer",
    "entrypoint",
    "reachable",
    "runtime_rows",
    "last_activity",
    "dependencies",
    "security_risk",
    "business_value",
    "architectural_value",
    "duplication",
    "decision",
    "reason",
    "required_work",
    "tests_needed",
    "priority",
    "source_evidence",
}


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_all_72_source_findings_are_reviewed_exactly_once() -> None:
    source = _load(SOURCE)
    artifact = _load(ARTIFACT)
    expected = {
        item["id"]
        for item in source["findings"]  # type: ignore[index]
        if item["classification"] == "incomplete_subsystem"
    }
    reviews = artifact["reviews"]  # type: ignore[index]
    actual = [item["id"] for item in reviews]

    assert len(expected) == 72
    assert len(actual) == 72
    assert len(set(actual)) == 72
    assert set(actual) == expected
    assert artifact["source_incomplete_subsystem_count"] == 72
    assert artifact["reviewed_count"] == 72


def test_every_review_has_complete_contract_owner_and_one_valid_decision() -> None:
    artifact = _load(ARTIFACT)
    for review in artifact["reviews"]:  # type: ignore[index]
        assert REQUIRED_FIELDS <= review.keys()
        assert review["decision"] in DECISIONS
        assert review["group"] in {"A", "B", "C", "D", "E"}
        assert review["owner"]
        assert review["mission"]
        assert review["reason"]
        assert review["required_work"]
        assert review["tests_needed"]
        assert review["priority"] in {"P1", "P2", "P3"}
        assert review["security_risk"] in {"low", "medium", "high"}


def test_explicit_human_reviews_cover_the_49_unique_subsystems() -> None:
    artifact = _load(ARTIFACT)
    names = {review["name"] for review in artifact["reviews"]}  # type: ignore[index]
    assert len(names) == 49
    assert names == set(REVIEWS)
    assert artifact["unique_subsystem_count"] == 49
    assert sum(artifact["decision_counts"].values()) == 72
    assert set(artifact["decision_counts"]) == DECISIONS


def test_duplicate_detector_findings_are_symmetric_and_decision_consistent() -> None:
    artifact = _load(ARTIFACT)
    by_id = {item["id"]: item for item in artifact["reviews"]}  # type: ignore[index]
    for item in by_id.values():
        for duplicate_id in item["duplication"]["other_finding_ids"]:
            duplicate = by_id[duplicate_id]
            assert item["id"] in duplicate["duplication"]["other_finding_ids"]
            assert duplicate["name"] == item["name"]
            assert duplicate["decision"] == item["decision"]


def test_nothing_is_activated_without_the_full_productive_gate() -> None:
    artifact = _load(ARTIFACT)
    activated = [
        item
        for item in artifact["reviews"]  # type: ignore[index]
        if item["decision"] == "activate_now"
    ]
    assert activated == []
    assert artifact["activation_gate"]["activate_now_count"] == 0  # type: ignore[index]
    assert all(
        item["decision"] != "activate_now"
        for item in artifact["reviews"]  # type: ignore[index]
        if item["producer"] == ["not_demonstrated"]
        or item["consumer"] == ["not_demonstrated"]
        or item["entrypoint"] == "none"
    )


def test_no_experimental_subsystem_is_presented_as_productive() -> None:
    artifact = _load(ARTIFACT)
    experimental = [
        item
        for item in artifact["reviews"]  # type: ignore[index]
        if item["decision"] == "experimental_keep"
    ]
    assert len(experimental) == 17
    assert all("activate" not in item["decision"] for item in experimental)
    assert all(item["required_work"] for item in experimental)

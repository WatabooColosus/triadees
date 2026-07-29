from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.research.governed import GovernedResearchWorker


def source(host: str, value: str = "yes", **extra):
    return {
        "url": f"https://{host}/evidence",
        "title": host,
        "content": f"Independent evidence from {host}: {value}",
        "claims": [{"key": "claim-a", "value": value}],
        **extra,
    }


def run(worker: GovernedResearchWorker):
    return worker.run(
        question="Is claim A supported?",
        trigger="gap",
        scope="benchmark",
        allowed_sources=["one.test", "two.test", "three.test"],
    )


def test_one_source_is_insufficient_and_not_learning(tmp_path: Path) -> None:
    worker = GovernedResearchWorker(
        tmp_path / "research.db",
        lambda question, minimum: {"sources": [source("one.test")]},
    )
    result = run(worker)
    assert result["status"] == "insufficient_sources"
    assert result["candidate_id"] is None
    assert result["learning_validated"] is False


def test_duplicate_and_failed_sources_are_exposed(tmp_path: Path) -> None:
    worker = GovernedResearchWorker(
        tmp_path / "research.db",
        lambda question, minimum: {
            "sources": [source("one.test"), source("one.test")],
            "failures": [{"url": "https://two.test", "reason": "timeout"}],
        },
    )
    result = run(worker)
    reasons = {failure["reason"] for failure in result["source_failures"]}
    assert result["status"] == "insufficient_sources"
    assert reasons == {"timeout", "duplicate_not_independent"}


def test_conflict_is_not_resolved_by_majority(tmp_path: Path) -> None:
    worker = GovernedResearchWorker(
        tmp_path / "research.db",
        lambda question, minimum: {
            "sources": [
                source("one.test", "yes"),
                source("two.test", "no"),
                source("three.test", "yes"),
            ]
        },
    )
    result = run(worker)
    assert result["status"] == "conflicting_sources"
    assert result["contradictions"][0]["resolution"] == "unresolved"
    assert result["candidate_id"] is None


def test_independent_sources_create_candidate_only(tmp_path: Path) -> None:
    db_path = tmp_path / "research.db"
    worker = GovernedResearchWorker(
        db_path,
        lambda question, minimum: {"sources": [source("one.test"), source("two.test")]},
    )
    result = run(worker)
    assert result["status"] == "candidate_created"
    assert result["candidate_id"]
    assert result["stable_memory_written"] is False
    with sqlite3.connect(db_path) as conn:
        status = conn.execute(
            "SELECT status FROM learning_queue WHERE candidate_id = ?",
            (result["candidate_id"],),
        ).fetchone()[0]
    assert status == "candidate"


def test_inaccessible_self_generated_and_unallowed_sources_do_not_count(
    tmp_path: Path,
) -> None:
    worker = GovernedResearchWorker(
        tmp_path / "research.db",
        lambda question, minimum: {
            "sources": [
                source("one.test", accessible=False),
                source("two.test", source_type="system_generated"),
                source("outside.test"),
            ]
        },
    )
    result = run(worker)
    assert result["status"] == "insufficient_sources"
    assert len(result["source_failures"]) == 3

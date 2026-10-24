from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.research.governed import GovernedResearchWorker


def test_first_curriculum_query_initializes_research_history_without_fake_runs(
    tmp_path,
):
    from triade.workers.contracts import WorkerRunConfig, WorkerTask
    from triade.workers.worker_loop import WorkerLoop

    db = tmp_path / "first.db"
    loop = WorkerLoop(
        db_path=db,
        runs_dir=tmp_path / "runs",
        lock_file=tmp_path / "lock",
        stop_file=tmp_path / "stop",
    )
    result = loop._research_curriculum(
        WorkerTask(task_type="research_curriculum"),
        "first-query",
        tmp_path / "runs",
        WorkerRunConfig(),
    )
    assert result["reason"] == "no_neuronal_gap"
    with sqlite3.connect(db) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM governed_research_runs"
            ).fetchone()[0]
            == 0
        )


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


def test_topic_excerpts_do_not_claim_a_contradiction(tmp_path: Path) -> None:
    sources = [source("one.test"), source("two.test")]
    sources[0]["claims"] = [
        {
            "key": "testing",
            "value": "A test case checks one behavior.",
            "claim_type": "relevant_excerpt",
        }
    ]
    sources[1]["claims"] = [
        {
            "key": "testing",
            "value": "Continuous integration runs a suite.",
            "claim_type": "relevant_excerpt",
        }
    ]
    worker = GovernedResearchWorker(
        tmp_path / "research.db", lambda question, minimum: {"sources": sources}
    )
    result = run(worker)
    assert result["contradictions"] == []
    assert result["learning_validated"] is False
    assert result["candidate_id"]


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

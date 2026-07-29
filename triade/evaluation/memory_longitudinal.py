"""Benchmark reproducible de memoria longitudinal gobernada."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from triade.memory.longitudinal import (
    LongitudinalMemory,
    MemoryObservation,
    MemoryScope,
)


def _promote(store: LongitudinalMemory, memory_id: str) -> None:
    store.transition(
        memory_id,
        "verified",
        actor="independent-evaluator:benchmark",
        reason="Fixture provenance independently checked.",
        evidence_ref=f"benchmark-evidence:{memory_id}",
    )


def run_memory_longitudinal_benchmark(root: str | Path | None = None) -> dict[str, Any]:
    owned_tmp: tempfile.TemporaryDirectory[str] | None = None
    if root is None:
        owned_tmp = tempfile.TemporaryDirectory(prefix="triade-memory-longitudinal-")
        base = Path(owned_tmp.name)
    else:
        base = Path(root)
        base.mkdir(parents=True, exist_ok=True)
    store = LongitudinalMemory(base / "memory.db")
    scopes = {
        "alice_atlas": MemoryScope("alice", "alice-session", "atlas", "work"),
        "alice_orion": MemoryScope("alice", "alice-session", "orion", "work"),
        "bob_atlas": MemoryScope("bob", "bob-session", "atlas", "work"),
    }
    fixtures = (
        ("alice_atlas", "preference", "editor", "Neovim"),
        ("alice_atlas", "restriction", "backup", "Backup before migration"),
        ("alice_atlas", "decision", "database", "Use SQLite"),
        ("alice_orion", "fact", "language", "Rust"),
        ("bob_atlas", "preference", "editor", "VS Code"),
    )
    expected: dict[tuple[str, str], str] = {}
    for index, (scope_name, memory_type, key, value) in enumerate(fixtures):
        stored = store.observe(
            MemoryObservation(
                memory_type,
                key,
                value,
                source_ref=f"fixture:{index}",
                confidence=1.0,
            ),
            scopes[scope_name],
        )
        _promote(store, stored["memory_id"])
        expected[(scope_name, key)] = value

    queries = (
        ("alice_atlas", "editor", "editor"),
        ("alice_atlas", "backup", "backup"),
        ("alice_atlas", "database", "database"),
        ("alice_orion", "language", "language"),
        ("bob_atlas", "editor", "editor"),
    )
    true_positive = false_positive = false_negative = 0
    query_results: list[dict[str, Any]] = []
    for scope_name, query, key in queries:
        recalled = store.recall(query, scopes[scope_name])
        values = [str(item["memory_value"]) for item in recalled]
        wanted = expected[(scope_name, key)]
        hits = sum(value == wanted for value in values)
        true_positive += hits
        false_positive += len(values) - hits
        false_negative += int(hits == 0)
        query_results.append(
            {
                "scope": scope_name,
                "query": query,
                "expected": wanted,
                "retrieved": values,
                "explanations": [item["why_retrieved"] for item in recalled],
            }
        )

    contamination_checks = 0
    contamination = 0
    for source_name, target_name, query in (
        ("alice_atlas", "bob_atlas", "editor"),
        ("bob_atlas", "alice_atlas", "editor"),
        ("alice_atlas", "alice_orion", "backup"),
    ):
        source_value = expected[(source_name, query)]
        recalled = store.recall(query, scopes[target_name])
        contamination_checks += 1
        contamination += sum(item["memory_value"] == source_value for item in recalled)

    correction = store.observe(
        MemoryObservation(
            "decision",
            "database",
            "Use PostgreSQL",
            source_ref="correction:database",
            confidence=1.0,
        ),
        scopes["alice_atlas"],
    )
    contradiction_detected = int(correction["contradiction_detected"])
    _promote(store, correction["memory_id"])

    expired_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    temporal = store.observe(
        MemoryObservation(
            "temporal",
            "temporary_branch",
            "feature/old",
            source_ref="temporal:fixture",
            expires_at=expired_at,
        ),
        scopes["alice_atlas"],
    )
    _promote(store, temporal["memory_id"])
    expired = store.expire()
    expired_hidden = not store.recall("temporary_branch", scopes["alice_atlas"])

    restarted = LongitudinalMemory(base / "memory.db")
    restart_recall = restarted.recall("database", scopes["alice_atlas"])
    restart_ok = [item["memory_value"] for item in restart_recall] == ["Use PostgreSQL"]

    backup = restarted.backup(base / "backup" / "memory.db")
    restore = LongitudinalMemory.restore_to_sandbox(
        backup["path"], base / "restore" / "memory.db", backup["fingerprint"]
    )

    precision = true_positive / max(true_positive + false_positive, 1)
    recall = true_positive / max(true_positive + false_negative, 1)
    hallucinated_rate = false_positive / max(true_positive + false_positive, 1)
    contamination_rate = contamination / max(contamination_checks, 1)
    contradiction_rate = contradiction_detected / 1
    restore_fidelity = float(restore["status"] == "verified")
    metrics = {
        "precision": precision,
        "recall": recall,
        "hallucinated_memory_rate": hallucinated_rate,
        "cross_user_contamination": contamination_rate,
        "contradiction_detection": contradiction_rate,
        "restore_fidelity": restore_fidelity,
    }
    thresholds = {
        "precision": precision >= 0.95,
        "hallucinated_memory_rate": hallucinated_rate < 0.01,
        "cross_user_contamination": contamination_rate == 0.0,
        "contradiction_detection": contradiction_rate >= 0.90,
        "restore_fidelity": restore_fidelity == 1.0,
    }
    result = {
        "benchmark": "TRIADE-MEMORY-LONGITUDINAL-v1",
        "metrics": metrics,
        "thresholds": thresholds,
        "query_results": query_results,
        "temporal": {
            "expired_ids": expired,
            "expired_memory_hidden": expired_hidden,
        },
        "restart_retention": restart_ok,
        "restore": restore,
        "passed": all(thresholds.values()) and expired_hidden and restart_ok,
    }
    if owned_tmp is not None:
        owned_tmp.cleanup()
    return result

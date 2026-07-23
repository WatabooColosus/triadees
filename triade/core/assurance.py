"""Estado compacto de garantías operativas basado en evidencia persistida."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from triade.evaluation.external_benchmark import FrozenBenchmarkRegistry
from triade.learning.novelty import LearningNoveltyGate
from triade.planning.goal_graph import DurableGoalGraph
from triade.workers.state_store import WorkerStateStore


def build_assurance_status(db_path: str | Path = "triade/memory/triade.db") -> dict[str, Any]:
    db_path = Path(db_path)
    FrozenBenchmarkRegistry(db_path)
    DurableGoalGraph(db_path)
    novelty = LearningNoveltyGate(db_path)
    workers = WorkerStateStore(db_path).status()
    queries = {
        "scoped_runs": "SELECT COUNT(*) FROM runs WHERE tenant_id!='legacy' AND user_id!='legacy' AND session_id!='legacy'",
        "frozen_benchmarks": "SELECT COUNT(*) FROM frozen_benchmarks",
        "external_runs": "SELECT COUNT(*) FROM external_benchmark_runs",
        "durable_goals": "SELECT COUNT(*) FROM durable_goals",
        "external_ab_pairs": "SELECT COUNT(*) FROM ab_external_evaluations",
        "evaluated_neurons": "SELECT COUNT(*) FROM neuron_eval_metrics WHERE total_activations>0",
        "federated_envelopes": "SELECT COUNT(*) FROM federated_exchanges_v2",
    }
    counts: dict[str, int] = {}
    with sqlite3.connect(db_path) as conn:
        existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for key, query in queries.items():
            table = query.split(" FROM ", 1)[1].split()[0]
            counts[key] = int(conn.execute(query).fetchone()[0]) if table in existing else 0
    return {
        "status": "ok",
        "evidence_counts": counts,
        "worker_execution": workers.get("execution", {}),
        "learning_novelty": novelty.metrics(),
        "controls": {
            "principal_scope": "tenant_user_session_required_in_storage",
            "benchmark": "immutable_manifest_external_evaluator",
            "planning": "sqlite_goal_dag_with_leases_and_replanning",
            "model_selection": "external_frozen_benchmark_only_for_runtime_override",
            "neuron_evaluation": "observed_activation_outcomes",
            "federation": "signed_ttl_replay_safe_idempotent_envelopes",
            "code_sandbox": "detached_git_worktree_allowlisted_tests",
            "rollback": "reset_and_clean_isolated_worktree_on_regression",
            "worker_telemetry": "shared_sqlite_lease",
            "candidate_novelty": "persistent_fingerprint_and_jaccard_gate",
        },
    }

from __future__ import annotations

import subprocess
from pathlib import Path

from triade.core.bodega import Bodega
from triade.core.contracts import InputPacket, OutputPacket
from triade.core.neuron_evaluator import NeuronEvaluator
from triade.core.config import load_config
from triade.evaluation.external_benchmark import FrozenBenchmarkRegistry
from triade.federation import (
    FederatedEnvelope,
    FederatedExchangeStore,
    FederatedNodeIdentity,
    FederatedNodeRegistry,
    HMACEnvelopeAuthenticator,
)
from triade.learning.novelty import LearningNoveltyGate
from triade.models.ab_model_evaluator import ABModelEvaluator
from triade.planning.goal_graph import DurableGoalGraph
from triade.sandbox.code_worktree import CodeWorktreeSandbox
from triade.workers.state_store import WorkerStateStore


def _packet(text: str, user: str, session: str = "conversation") -> InputPacket:
    return InputPacket(
        text,
        source="web",
        context={"tenant_id": "wataboo", "user_id": user, "session_id": session},
    )


def test_runtime_config_parses_explicit_worker_learning_task_allowlist(tmp_path: Path) -> None:
    config = tmp_path / "triade.yml"
    config.write_text("runtime:\n  worker_learning_tasks_enabled: true\n  worker_enabled_tasks: [pulse_check, pending_learning_review]\n", encoding="utf-8")
    runtime = load_config(config)["runtime"]
    assert runtime["worker_learning_tasks_enabled"] is True
    assert runtime["worker_enabled_tasks"] == ["pulse_check", "pending_learning_review"]


def test_memory_survives_restart_and_is_isolated_by_principal(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    first = Bodega(db)
    alice = _packet("Mi nombre es Santiago", "alice")
    bob = _packet("Mi nombre es Roberto", "bob")
    for packet, answer in ((alice, "Hola Santiago"), (bob, "Hola Roberto")):
        first.create_run(packet)
        first.store_episode(packet, OutputPacket(run_id=packet.run_id, response=answer))

    restarted = Bodega(db)
    alice_memory = restarted.recall(_packet("nombre Santiago", "alice"))
    bob_memory = restarted.recall(_packet("nombre Santiago", "bob"))
    assert any("Santiago" in item["summary"] for item in alice_memory.episodic_matches)
    assert all("Santiago" not in item["summary"] for item in bob_memory.episodic_matches)
    assert alice_memory.semantic_recall["principal_scope"]["user_id"] == "alice"


def test_frozen_external_benchmark_drives_ab_recommendation(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    registry = FrozenBenchmarkRegistry(db)
    manifest = {"benchmark_id": "external-v1", "version": "1", "cases": [{"id": "remember", "input": "x"}]}
    frozen = registry.freeze(manifest)
    assert registry.freeze(manifest) == frozen
    registry.record_external_run(run_id="run-a", benchmark_id="external-v1", version="1", subject_id="model-a",
                                 evaluator_id="independent-lab", score=0.62, metrics={"pass": 1}, artifact={"signed": "a"})
    registry.record_external_run(run_id="run-b", benchmark_id="external-v1", version="1", subject_id="model-b",
                                 evaluator_id="independent-lab", score=0.84, metrics={"pass": 1}, artifact={"signed": "b"})
    result = ABModelEvaluator(db).record_external_pair(task_type="central", model_a="model-a", benchmark_run_a="run-a",
                                                       model_b="model-b", benchmark_run_b="run-b")
    recommendation = ABModelEvaluator(db).get_recommendation("central")
    assert result["winner"] == "model-b"
    assert recommendation["recommended_model"] == "model-b"
    assert recommendation["evidence_method"] == "external_frozen_benchmark"


def test_goal_graph_survives_restart_and_replans(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    graph = DurableGoalGraph(db)
    parent = graph.create(goal_id="goal-parent", title="Preparar", tenant_id="wataboo", user_id="alice", acceptance=["evidence"])
    graph.create(goal_id="goal-child", title="Ejecutar", tenant_id="wataboo", user_id="alice",
                 acceptance=["tests pass"], dependencies=[parent["goal_id"]])
    assert [goal["goal_id"] for goal in graph.ready("wataboo", "alice")] == [parent["goal_id"]]
    assert graph.acquire("goal-parent", "worker-a")
    graph.complete("goal-parent", "worker-a", ["artifact://parent"])

    restarted = DurableGoalGraph(db)
    assert restarted.ready("wataboo", "alice")[0]["goal_id"] == "goal-child"
    assert restarted.acquire("goal-child", "worker-b")
    replanned = restarted.fail_and_replan("goal-child", "worker-b", "regression", ["tests pass", "no regression"])
    assert replanned["status"] == "replanned" and replanned["plan_version"] == 2
    assert restarted.acquire("goal-child", "worker-b")
    assert restarted.complete("goal-child", "worker-b", ["artifact://green"])["status"] == "completed"


def test_neuron_evaluation_uses_observed_outcomes(tmp_path: Path) -> None:
    evaluator = NeuronEvaluator(tmp_path / "triade.db")
    evaluator.record_activation(7, "verifier", score=0.9, success=True, response_ms=12, source="mission")
    evaluator.record_activation(7, "verifier", score=0.2, success=False, response_ms=30, source="mission")
    metrics = evaluator.get_neuron_metrics(7)
    assert metrics and metrics["total_activations"] == 2
    assert metrics["successful_activations"] == 1 and metrics["failed_activations"] == 1
    assert metrics["avg_score"] == 0.55


def test_two_independent_nodes_exchange_signed_idempotent_envelope(tmp_path: Path) -> None:
    secret = b"federation-shared-secret-32-bytes!!"
    now = 1_900_000_000
    db_a, db_b = tmp_path / "node-a.db", tmp_path / "node-b.db"
    registry_b = FederatedNodeRegistry(db_b)
    registry_b.register(FederatedNodeIdentity(node_id="node-a", display_name="A", endpoint="local://a",
                                              public_key="key-a", capabilities=("goal_sync",), permissions=("submit_work",)))
    registry_b.transition("node-a", "trusted", actor="operator", reason="key verified", trust_score=0.9)
    auth_a = HMACEnvelopeAuthenticator(lambda _node: secret)
    receiver_b = FederatedExchangeStore(db_b, local_node_id="node-b", authenticator=auth_a, clock=lambda: now)
    envelope = auth_a.sign(FederatedEnvelope(message_id="a-to-b-1", sender_node_id="node-a", recipient_node_id="node-b",
                                              capability="goal_sync", permission="submit_work", nonce="unique-1",
                                              issued_at=now - 1, expires_at=now + 60, payload={"goal_id": "goal-1"}))
    assert receiver_b.accept(envelope)["idempotent"] is False
    assert receiver_b.accept(envelope)["idempotent"] is True
    assert db_a != db_b and receiver_b.get("a-to-b-1")["envelope"]["payload"]["goal_id"] == "goal-1"


def test_worktree_regression_causes_rollback_without_touching_base(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
    (repo / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "test_value.py").write_text("from value import VALUE\n\ndef test_value():\n    assert VALUE == 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    patch = """diff --git a/value.py b/value.py
index 7a66c46..7e20fdb 100644
--- a/value.py
+++ b/value.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""
    result = CodeWorktreeSandbox(repo).run_patch(patch, tests=["pytest_quick"])
    assert result["status"] == "rolled_back"
    assert result["rollback_reason"] == "regression:pytest_quick"
    assert (repo / "value.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_shared_worker_lease_and_novelty_metrics_persist(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    writer = WorkerStateStore(db)
    writer.heartbeat_execution("worker-1", ttl_seconds=60)
    assert WorkerStateStore(db).status()["execution"]["alive"] is True
    gate = LearningNoveltyGate(db)
    first = gate.assess("aprender memoria contextual durable", "memory")
    gate.register("candidate-1", "aprender memoria contextual durable", "memory")
    second = LearningNoveltyGate(db).assess("memoria contextual durable aprender", "memory")
    assert first["novel"] is True and second["novel"] is False
    assert LearningNoveltyGate(db).metrics()["duplicates"] == 1

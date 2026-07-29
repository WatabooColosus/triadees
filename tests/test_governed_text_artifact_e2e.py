from __future__ import annotations

import hashlib
import json
from pathlib import Path

from triade.capabilities.registry import CapabilityDefinition, CapabilityRegistry
from triade.core.central import PlanGraph, PlanStep
from triade.runtime.governed_capability import GovernedFileWriteCapability
from triade.runtime.governed_plan_dispatcher import GovernedPlanDispatcher
from triade.workers.contracts import WorkerRunConfig
from triade.workers.worker_loop import WorkerLoop


def test_governed_text_artifact_full_lifecycle(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    target = tmp_path / "authorized" / "result.txt"
    target.parent.mkdir()
    CapabilityRegistry(db_path).register(
        CapabilityDefinition(
            capability_id="write_governed_text_artifact",
            name="Governed text artifact", domain="runtime", version="1",
            owner="central", component="worker_loop", state="active",
            rollback_policy="verified_file_rollback",
            input_contract={"type": "object"}, output_contract={"type": "object"},
            permissions=("execute",),
        )
    )
    step = PlanStep(
        id="write", description="ejecuta write_governed_text_artifact", priority=0,
        result={
            "dispatch_payload": {
                "target": str(target), "content": "contenido gobernado",
                "authorized_root": str(target.parent),
            }
        },
    )
    graph = PlanGraph(plan_id="plan-governed-write", goal="write", steps=[step])
    dispatcher = GovernedPlanDispatcher(db_path)
    dispatch = dispatcher.dispatch(graph, step)
    assert dispatch.status == "queued" and dispatch.task_id

    loop = WorkerLoop(
        db_path=db_path, runs_dir=tmp_path / "runs",
        lock_file=tmp_path / "worker.lock", stop_file=tmp_path / "stop",
    )
    loop.run(
        WorkerRunConfig(
            once=True, max_iterations=1, max_tasks_per_drain=1,
            runs_dir=str(tmp_path / "runs"), lock_file=str(tmp_path / "worker.lock"),
            stop_file=str(tmp_path / "stop"),
        )
    )
    task = dispatcher.tasks.get(dispatch.task_id)
    assert task and task["status"] == "completed"
    assert target.read_text(encoding="utf-8") == "contenido gobernado"
    assert hashlib.sha256(target.read_bytes()).hexdigest() == hashlib.sha256(
        b"contenido gobernado"
    ).hexdigest()

    result_ref = Path(str(task["result_ref"]))
    assert result_ref.is_file()
    task_dir = result_ref.parent
    assert (task_dir / "manifest.json").is_file()
    assert (task_dir / "evidence.json").is_file()
    result = json.loads(result_ref.read_text(encoding="utf-8"))
    assert result["effect_receipt"]["verified"] is True

    dispatcher.synchronize(graph)
    assert step.state == "completed"
    assert graph.status == "completed"

    rollback = GovernedFileWriteCapability.rollback_from_spec(result["rollback_spec"])
    assert rollback.verified
    assert not target.exists()
    assert Path(str(rollback.rollback_ref)).is_file()

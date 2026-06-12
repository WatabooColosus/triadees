"""Loop controlado de Triade Living Workers."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

from triade.core.background_neurons import candidates_from_system_debt
from triade.core.contracts import CrystalPacket, MemoryPacket, PlanPacket, SignalPacket, utc_now
from triade.core.experimental_neuron_runtime import run_experimental_neurons
from triade.core.neuron_activity_store import NeuronActivityStore
from triade.core.neuron_autopromoter import NeuronAutopromoter
from triade.core.neuron_formation_pipeline import form_candidates
from triade.core.safety import Safety
from triade.federation.federation import Federation
from triade.learning.pipeline import LearningPipeline
from triade.memory.semantic_governance import SemanticMemoryGovernance
from triade.memory.semantic_store import SemanticMemoryStore

from .contracts import WORKER_TASK_TYPES, WorkerRunConfig, WorkerTask, new_worker_run_id
from .scheduler import WorkerScheduler
from .state_store import WorkerStateStore
from .task_queue import WorkerTaskQueue


class WorkerSandbox:
    """Sandbox local: tareas internas conocidas, sin shell ni red."""

    ALLOWED_TASKS = {"validate_learning_candidate", "analyze_memory_candidate", "json_validation", "internal_diagnostic"}

    def __init__(self, artifact_dir: str | Path) -> None:
        self.artifact_dir = Path(artifact_dir)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def run(self, task: str, payload: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        if task not in self.ALLOWED_TASKS:
            return {"status": "blocked", "task": task, "reason": "sandbox_task_not_allowed"}
        started = time.monotonic()
        result: dict[str, Any] = {"status": "ok", "task": task, "network": False, "shell": False}
        try:
            if task == "validate_learning_candidate":
                content = str(payload.get("content") or "")
                result.update({
                    "content_length": len(content),
                    "has_source_ref": bool(payload.get("source_ref")),
                    "identity_red_flag": any(flag in content.lower() for flag in ("modificar identidad", "borrar memoria", "identity_core")),
                })
            elif task == "analyze_memory_candidate":
                result.update({"stable_write": False, "candidate_only": True, "source_ref": payload.get("source_ref")})
            elif task == "json_validation":
                json.dumps(payload)
                result["valid_json"] = True
            else:
                result["diagnostic"] = "completed"
        except Exception as exc:
            result = {"status": "error", "task": task, "error": str(exc)}
        result["elapsed"] = round(time.monotonic() - started, 4)
        if result["elapsed"] > timeout:
            result = {"status": "timeout", "task": task, "timeout": timeout}
        (self.artifact_dir / f"sandbox-{task}-{int(time.time() * 1000)}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result


class WorkerLoop:
    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        runs_dir: str | Path = "runs/background",
        lock_file: str | Path = ".triade_workers.lock",
        stop_file: str | Path = ".triade_stop",
    ) -> None:
        self.db_path = Path(db_path)
        self.runs_dir = Path(runs_dir)
        self.lock_file = Path(lock_file)
        self.stop_file = Path(stop_file)
        self.store = WorkerStateStore(db_path=self.db_path)
        self.queue = WorkerTaskQueue(db_path=self.db_path)
        self.scheduler = WorkerScheduler(db_path=self.db_path)

    def run(self, config: WorkerRunConfig | None = None) -> dict[str, Any]:
        config = config or WorkerRunConfig(runs_dir=str(self.runs_dir), lock_file=str(self.lock_file), stop_file=str(self.stop_file))
        self.runs_dir = Path(config.runs_dir)
        self.lock_file = Path(config.lock_file)
        self.stop_file = Path(config.stop_file)
        if self.lock_file.exists():
            return {"status": "locked", "lock_file": str(self.lock_file), "message": "Worker ya está en ejecución."}
        if self.stop_file.exists():
            return {"status": "stopped", "stop_file": str(self.stop_file), "message": "Stop file presente antes de iniciar."}

        self.lock_file.write_text(str(os.getpid()), encoding="utf-8")
        run_ref = new_worker_run_id()
        artifact_dir = self._artifact_dir(run_ref)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        summary: dict[str, Any] = {"run_ref": run_ref, "iterations": 0, "tasks_completed": 0, "tasks_blocked": 0, "errors": []}
        self.store.create_worker_run(run_ref, config, artifact_dir)
        self.store.set_state("workers", {"status": "running", "run_ref": run_ref, "started_at": utc_now(), "config": config.to_dict()})

        try:
            for iteration in range(max(1, int(config.max_iterations))):
                if self.stop_file.exists():
                    summary["stop_requested"] = True
                    break
                summary["iterations"] += 1
                self.scheduler.schedule_cycle(run_ref, config)
                while True:
                    task = self.queue.claim_next()
                    if task is None:
                        break
                    if task.run_ref and task.run_ref != run_ref:
                        self.store.finish_task(task.id or 0, "skipped", {"reason": "belongs_to_other_run"}, run_ref=task.run_ref)
                        continue
                    result = self._execute_task(task, run_ref, artifact_dir, config)
                    if result.get("status") == "blocked":
                        summary["tasks_blocked"] += 1
                    elif result.get("status") == "error":
                        summary["errors"].append(result.get("error"))
                    else:
                        summary["tasks_completed"] += 1
                if config.once:
                    break
                if iteration < int(config.max_iterations) - 1:
                    time.sleep(max(0.0, float(config.sleep_seconds)))
            status = "completed" if not summary.get("errors") else "completed_with_errors"
            self.store.finish_worker_run(run_ref, status, summary)
            self.store.set_state("workers", {"status": status, "last_run_ref": run_ref, "finished_at": utc_now(), "summary": summary})
            (artifact_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"status": status, "run_ref": run_ref, "artifact_dir": str(artifact_dir), **summary}
        except Exception as exc:
            summary["errors"].append(str(exc))
            self.store.finish_worker_run(run_ref, "failed", summary, error=str(exc))
            self.store.set_state("workers", {"status": "failed", "last_run_ref": run_ref, "error": str(exc), "finished_at": utc_now()})
            return {"status": "failed", "run_ref": run_ref, "artifact_dir": str(artifact_dir), "error": str(exc), **summary}
        finally:
            try:
                self.lock_file.unlink()
            except FileNotFoundError:
                pass

    def request_stop(self) -> dict[str, Any]:
        self.stop_file.write_text(utc_now(), encoding="utf-8")
        self.store.set_state("workers", {"status": "stop_requested", "stop_file": str(self.stop_file), "at": utc_now()})
        return {"status": "stop_requested", "stop_file": str(self.stop_file)}

    def clear_stop(self) -> None:
        try:
            self.stop_file.unlink()
        except FileNotFoundError:
            pass

    def _execute_task(self, task: WorkerTask, run_ref: str, artifact_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
        started = time.monotonic()
        safety = self._safety_for_task(task, run_ref)
        task_dir = artifact_dir / f"task-{task.id}-{task.task_type}"
        task_dir.mkdir(parents=True, exist_ok=True)
        base = {"task": task.to_dict(), "safety": safety.to_dict(), "dry_run": config.dry_run, "started_at": utc_now()}
        (task_dir / "input.json").write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")

        if safety.status == "blocked" or safety.human_approval_required:
            result = {"status": "blocked", "reason": safety.reason, "safety_status": safety.status}
            self.store.finish_task(task.id or 0, "blocked", result, safety.status, run_ref=run_ref)
            self.store.record_event("task_blocked", safety.reason, run_ref=run_ref, task_id=task.id, task_type=task.task_type, status="blocked", payload=result)
        elif config.dry_run:
            result = {"status": "dry_run", "task_type": task.task_type, "would_execute": True}
            self.store.finish_task(task.id or 0, "completed", result, safety.status, run_ref=run_ref)
        else:
            try:
                handlers: dict[str, Callable[[WorkerTask, str, Path, WorkerRunConfig], dict[str, Any]]] = {
                    "pulse_check": self._pulse_check,
                    "pending_learning_review": self._pending_learning_review,
                    "semantic_memory_governance": self._semantic_memory_governance,
                    "neuron_candidate_formation": self._neuron_candidate_formation,
                    "experimental_neuron_activity": self._experimental_neuron_activity,
                    "neuron_autopromotion": self._neuron_autopromotion,
                    "federation_inbox_review": self._federation_inbox_review,
                    "memory_consolidation_review": self._memory_consolidation_review,
                    "system_debt_scan": self._system_debt_scan,
                }
                result = handlers[task.task_type](task, run_ref, task_dir, config)
                if time.monotonic() - started > config.task_timeout:
                    raise TimeoutError(f"worker task timeout: {task.task_type}")
                self.store.finish_task(task.id or 0, result.get("status", "completed"), result, safety.status, run_ref=run_ref)
                self.store.record_event("task_completed", f"{task.task_type} completada", run_ref=run_ref, task_id=task.id, task_type=task.task_type, payload=result)
            except Exception as exc:
                result = {"status": "error", "task_type": task.task_type, "error": str(exc)}
                self.store.finish_task(task.id or 0, "failed", result, safety.status, error=str(exc), run_ref=run_ref)
                self.store.record_event("task_failed", str(exc), run_ref=run_ref, task_id=task.id, task_type=task.task_type, status="error", payload=result)
        result["elapsed"] = round(time.monotonic() - started, 4)
        (task_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def _safety_for_task(self, task: WorkerTask, run_ref: str):
        signals = SignalPacket(run_id=run_ref, intent="worker", tone="operational", urgency="low", risk="low", pv7={}, notes=[task.task_type])
        plan = PlanPacket(run_id=run_ref, goal=f"Ejecutar worker task {task.task_type}", steps=["safe_background_cycle"], tools=[])
        memory = MemoryPacket(run_id=run_ref, semantic_recall={"enabled": False})
        crystal = CrystalPacket(run_id=run_ref, temporal_status="stable")
        return Safety().review(signals, plan, crystal=crystal, memory=memory)

    def _pulse_check(self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
        from apps.services import build_system_pulse
        pulse = build_system_pulse(sync_relay=False)
        return {"status": "completed", "pulse": pulse, "policy": "local_only_no_external_relay_sync"}

    def _pending_learning_review(self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
        pipe = LearningPipeline(db_path=self.db_path)
        sandbox = WorkerSandbox(task_dir)
        processed = []
        for candidate in pipe.list_candidates(status="candidate", limit=5):
            sb = sandbox.run("validate_learning_candidate", candidate, timeout=config.task_timeout)
            if sb.get("identity_red_flag"):
                processed.append(pipe.reject(candidate["candidate_id"], reason="worker sandbox detected identity_core risk"))
            else:
                processed.append(pipe.evaluate(candidate["candidate_id"]))
        for candidate in pipe.list_candidates(status="evaluated", limit=5):
            processed.append(pipe.verify(candidate["candidate_id"]))
        return {"status": "completed", "processed_count": len(processed), "processed": processed, "stable_memory_written": False}

    def _semantic_memory_governance(self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
        return {"status": "completed", "governance": SemanticMemoryGovernance(db_path=self.db_path).doctor()}

    def _neuron_candidate_formation(self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
        pulse = {"status": "unknown", "summary": "worker background scan", "federation": {"android_native_online": 0, "android_llm_hosts": 0}}
        raw = candidates_from_system_debt(pulse_summary=pulse)
        formed = form_candidates(raw)
        return {"status": "completed", "raw_count": len(raw), "formed_count": len(formed), "candidates": formed}

    def _experimental_neuron_activity(self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
        signals = SignalPacket(run_id=run_ref, intent="worker", tone="operational", urgency="low", risk="low", notes=["background"])
        activity = run_experimental_neurons(
            db_path=str(self.db_path),
            user_input="pulso memoria federacion modelo estado worker",
            context={"domain": "system_governance", "active_neuron": "living-workers"},
            signals=signals,
            edge_usage={"used_edge": False, "accepted": False, "keywords": ["pulso", "memoria", "federacion"]},
            system_events=[],
        )
        ids = NeuronActivityStore(db_path=self.db_path).record_run_activity(run_ref, activity)
        activity["db_activity_ids"] = ids
        return {"status": "completed", "activity": activity}

    def _neuron_autopromotion(self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
        events = NeuronAutopromoter(db_path=self.db_path).promote()
        return {"status": "completed", "events": events, "stable_promotion_requires_readiness": True}

    def _federation_inbox_review(self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
        federation = Federation(db_path=self.db_path)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT exchange_id, source_node_id, target_node_id, exchange_type, risk_level, safety_status, decision, reason, created_at FROM federated_exchange_log ORDER BY id DESC LIMIT 10"
            ).fetchall()
        return {"status": "completed", "doctor": federation.doctor(), "recent_exchanges": [dict(row) for row in rows], "external_network": False}

    def _memory_consolidation_review(self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
        pipe = LearningPipeline(db_path=self.db_path)
        store = SemanticMemoryStore(db_path=self.db_path)
        governance = SemanticMemoryGovernance(db_path=self.db_path)
        sandbox = WorkerSandbox(task_dir)
        promoted = []
        for candidate in pipe.list_candidates(status="verified", limit=5):
            sb = sandbox.run("analyze_memory_candidate", candidate, timeout=config.task_timeout)
            if sb.get("status") != "ok" or not candidate.get("source_ref"):
                continue
            document = store.upsert_document(
                content=str(candidate.get("content") or ""),
                domain=str(candidate.get("domain") or "worker-learning"),
                source_type="worker_learning_review",
                source_ref=str(candidate.get("source_ref")),
                metadata={"learning_candidate_id": candidate.get("candidate_id"), "worker_run": run_ref},
                status="candidate",
            )
            try:
                transition = governance.transition_document(
                    document.document_id,
                    "experimental",
                    reason="Worker revisó candidato verified y lo deja como memoria experimental, no estable.",
                    approved_by="triade-worker-experimental-policy",
                    evidence={"worker_run": run_ref, "candidate_id": candidate.get("candidate_id")},
                )
            except ValueError as exc:
                transition = {"status": "skipped", "reason": str(exc), "document_id": document.document_id}
            promoted.append({"candidate_id": candidate.get("candidate_id"), "document_id": document.document_id, "transition": transition})
        return {"status": "completed", "experimental_memory_promotions": promoted, "stable_memory_written": False}

    def _system_debt_scan(self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
        pipe = LearningPipeline(db_path=self.db_path)
        content = "Worker detectó deuda operacional: mantener vivo el ciclo observar→evaluar→sandbox→memoria experimental→medición."
        candidate = pipe.ingest(
            content=content,
            source_type="tool",
            source_ref=f"worker:{run_ref}",
            title="Deuda operacional detectada por Living Workers",
            domain="living-workers",
            risk_level="low",
        )
        return {"status": "completed", "learning_candidate": candidate}

    def _artifact_dir(self, run_ref: str) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return self.runs_dir / f"{stamp}-{run_ref[-8:]}"

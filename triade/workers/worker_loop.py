"""Loop controlado de Triade Living Workers."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from triade.core.background_neurons import candidates_from_system_debt
from triade.core.contracts import (
    CrystalPacket,
    MemoryPacket,
    PlanPacket,
    SignalPacket,
    utc_now,
)
from triade.core.error_bus import record_internal_error
from triade.core.experimental_neuron_runtime import run_experimental_neurons
from triade.core.neuron_activity_store import NeuronActivityStore
from triade.core.neuron_autopromoter import NeuronAutopromoter
from triade.core.neuron_formation_pipeline import form_candidates
from triade.core.ollama_blood import check_ollama_blood, ollama_blood_policy
from triade.core.safety import Safety
from triade.federation.federation import Federation
from triade.learning.pipeline import LearningPipeline
from triade.memory.semantic_governance import SemanticMemoryGovernance
from triade.memory.semantic_store import SemanticMemoryStore
from triade.qualia.bus import QualiaBus
from triade.qualia.contracts import NeuronExperience
from triade.runtime.atomic_completion import AtomicCompletionCoordinator
from triade.runtime.backpressure import QueueDrainBudget, RuntimeBackpressure
from triade.runtime.cancellation import CancellationToken
from triade.runtime.effect_receipt import EffectReceipt
from triade.runtime.event_scheduler import EventDrivenScheduler
from triade.runtime.execution_result import ExecutionResult
from triade.runtime.governed_task_executor import GovernedTaskExecutor
from triade.runtime.lease_heartbeat import LeaseHeartbeat
from triade.runtime.legacy_task_reconciler import LegacyTaskReconciler
from triade.runtime.live_heartbeat import LiveHeartbeat
from triade.runtime.process_lock import RuntimeProcessLock
from triade.runtime.resource_ledger import ResourceLedger, ResourceMeasurementCollector
from triade.runtime.task_artifacts import CanonicalTaskArtifacts
from triade.runtime.task_leases import AutonomousTaskStore
from triade.runtime.wake_bus import runtime_wake_event

from .adaptive_scheduler import AdaptiveScheduler
from .contracts import WorkerRunConfig, WorkerTask, new_worker_run_id
from .neuron_mission_executor import NeuronMissionExecutor
from .scheduler import WorkerScheduler
from .state_store import WorkerStateStore
from .task_queue import WorkerTaskQueue

WORKER_OPERATION_ERRORS = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
    TimeoutError,
    sqlite3.Error,
)


class WorkerSandbox:
    """Sandbox local: tareas internas conocidas, sin shell ni red."""

    ALLOWED_TASKS: ClassVar[set[str]] = {
        "validate_learning_candidate",
        "analyze_memory_candidate",
        "json_validation",
        "internal_diagnostic",
    }

    def __init__(self, artifact_dir: str | Path) -> None:
        self.artifact_dir = Path(artifact_dir)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self, task: str, payload: dict[str, Any], timeout: float = 30.0
    ) -> dict[str, Any]:
        if task not in self.ALLOWED_TASKS:
            return {
                "status": "blocked",
                "task": task,
                "reason": "sandbox_task_not_allowed",
            }
        started = time.monotonic()
        result: dict[str, Any] = {
            "status": "ok",
            "task": task,
            "network": False,
            "shell": False,
        }
        try:
            if task == "validate_learning_candidate":
                content = str(payload.get("content") or "")
                result.update(
                    {
                        "content_length": len(content),
                        "has_source_ref": bool(payload.get("source_ref")),
                        "identity_red_flag": any(
                            flag in content.lower()
                            for flag in (
                                "modificar identidad",
                                "borrar memoria",
                                "identity_core",
                            )
                        ),
                    }
                )
            elif task == "analyze_memory_candidate":
                result.update(
                    {
                        "stable_write": False,
                        "candidate_only": True,
                        "source_ref": payload.get("source_ref"),
                    }
                )
            elif task == "json_validation":
                json.dumps(payload)
                result["valid_json"] = True
            else:
                result["diagnostic"] = "completed"
        except (TypeError, ValueError) as exc:
            result = {"status": "error", "task": task, "error": str(exc)}
        result["elapsed"] = round(time.monotonic() - started, 4)
        if result["elapsed"] > timeout:
            result = {"status": "timeout", "task": task, "timeout": timeout}
        (
            self.artifact_dir / f"sandbox-{task}-{int(time.time() * 1000)}.json"
        ).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result


class WorkerLoop:
    READ_ONLY_TASKS_WITHOUT_BLOOD = frozenset(
        {
            "pulse_check",
            "pending_learning_review",
            "semantic_memory_governance",
            "federation_inbox_review",
            "bodega_global_review",
            "encrypted_backup",
        }
    )

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
        self.adaptive_scheduler = AdaptiveScheduler(db_path=self.db_path)
        self.resource_ledger = ResourceLedger(db_path=self.db_path)
        self.backpressure = RuntimeBackpressure(self.resource_ledger, disk_path=self.runs_dir)
        self.autonomous_tasks = AutonomousTaskStore(db_path=self.db_path)
        self.task_executor = GovernedTaskExecutor(
            quarantine_root=self.runs_dir / "quarantine" / "timeouts"
        )
        self.live_heartbeat = LiveHeartbeat(db_path=self.db_path)
        self.legacy_reconciler = LegacyTaskReconciler(self.db_path)

    def run(self, config: WorkerRunConfig | None = None) -> dict[str, Any]:
        config = config or WorkerRunConfig(
            runs_dir=str(self.runs_dir),
            lock_file=str(self.lock_file),
            stop_file=str(self.stop_file),
        )
        self.runs_dir = Path(config.runs_dir)
        self.task_executor = GovernedTaskExecutor(
            quarantine_root=self.runs_dir / "quarantine" / "timeouts"
        )
        self.lock_file = Path(config.lock_file)
        self.stop_file = Path(config.stop_file)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.stop_file.parent.mkdir(parents=True, exist_ok=True)
        if self.stop_file.exists():
            return {
                "status": "stopped",
                "stop_file": str(self.stop_file),
                "message": "Stop file presente antes de iniciar.",
            }

        recovery = self.store.recover_interrupted_runtime(self.lock_file)
        if recovery.get("status") == "live_owner":
            return {
                "status": "locked",
                "lock_file": str(self.lock_file),
                "pid": recovery.get("pid"),
                "message": "Worker ya está en ejecución.",
            }
        # Atomic lock: O_CREAT|O_EXCL evita carrera TOCTOU entre múltiples instancias.
        try:
            fd = os.open(
                str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
            )
            os.write(fd, RuntimeProcessLock.payload())
            os.close(fd)
        except FileExistsError:
            return {
                "status": "locked",
                "lock_file": str(self.lock_file),
                "message": "Worker ya está en ejecución.",
            }
        run_ref = new_worker_run_id()
        artifact_dir = self._artifact_dir(run_ref)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        blood = check_ollama_blood()
        blood_policy = ollama_blood_policy("worker_cycle", blood)
        from triade.services.event_bus import publish_event

        publish_event(
            "ollama_blood_checked",
            "worker_loop",
            {
                "status": blood.get("status"),
                "blood_pressure_score": blood.get("blood_pressure_score"),
            },
            db_path=self.db_path,
            run_ref=run_ref,
        )
        publish_event(
            "ollama_blood_active"
            if blood_policy.get("allowed") and not blood_policy.get("degraded")
            else "ollama_blood_degraded",
            "worker_loop",
            {
                "status": blood.get("status"),
                "degraded_components": blood.get("degraded_components", []),
            },
            severity="info"
            if blood_policy.get("allowed") and not blood_policy.get("degraded")
            else "warning",
            db_path=self.db_path,
            run_ref=run_ref,
        )
        summary: dict[str, Any] = {
            "run_ref": run_ref,
            "iterations": 0,
            "tasks_completed": 0,
            "tasks_blocked": 0,
            "errors": [],
            "ollama_blood_status": blood.get("status"),
            "model_used": blood.get("reasoning_model"),
            "degraded_mode": bool(blood_policy.get("degraded")),
            "cognitive_blood_active": bool(blood.get("cognitive_blood_active")),
            "runtime_recovery": recovery,
        }
        self.store.create_worker_run(run_ref, config, artifact_dir)
        self.store.set_state(
            "workers",
            {
                "status": "running",
                "run_ref": run_ref,
                "started_at": utc_now(),
                "config": config.to_dict(),
            },
        )

        try:
            self.legacy_reconciler.reconcile()
            wake_event = runtime_wake_event(self.db_path)
            live_scheduler = EventDrivenScheduler(wake_event=wake_event)

            def drain_queue() -> int:
                drained = 0
                budget = QueueDrainBudget(
                    max_tasks=config.max_tasks_per_drain,
                    max_seconds=config.max_seconds_per_drain,
                    per_type=config.max_tasks_per_type_per_drain,
                )
                # Los reintentos y tareas recuperadas v2 sobreviven aunque su
                # fila legacy ya no esté pendiente.
                while not budget.exhausted:
                    leased = self.autonomous_tasks.claim(
                        run_ref,
                        lease_seconds=max(60, int(config.task_timeout * 2)),
                        excluded_task_types=budget.excluded_types,
                    )
                    if leased is None:
                        break
                    drained += 1
                    budget.record(str(leased["task_type"]))
                    if not self.backpressure.allows(
                        str(leased["task_type"]), effectful=str(leased["task_type"]) not in self.READ_ONLY_TASKS_WITHOUT_BLOOD
                    ):
                        self.autonomous_tasks.defer(
                            str(leased["task_id"]), run_ref,
                            int(leased["lease_generation"]), "resource_backpressure",
                        )
                        continue
                    self._execute_autonomous_task(
                        leased, run_ref, artifact_dir, config, summary
                    )
                while not budget.exhausted:
                    task = self.queue.claim_next()
                    if task is None:
                        break
                    drained += 1
                    budget.record(task.task_type)
                    payload = dict(task.payload)
                    payload["_legacy_task_id"] = task.id
                    governed = self.autonomous_tasks.enqueue(
                        task.task_type,
                        payload,
                        idempotency_key=f"legacy-worker-task:{task.id}",
                        priority=task.priority,
                        max_attempts=3,
                    )
                    if not self.store.link_delegated_task(
                        int(task.id or 0), str(governed["task_id"])
                    ):
                        self.store.return_delegation_to_pending(
                            int(task.id or 0), "legacy_v2_link_rejected"
                        )
                        continue
                    leased = self.autonomous_tasks.claim_task(
                        str(governed["task_id"]),
                        run_ref,
                        lease_seconds=max(60, int(config.task_timeout * 2)),
                    )
                    if leased is None:
                        self.store.return_delegation_to_pending(
                            int(task.id or 0), "v2_lease_conflict"
                        )
                        self.store.record_event(
                            "task_lease_conflict",
                            "La tarea no pudo obtener lease v2",
                            run_ref=run_ref,
                            task_id=task.id,
                            task_type=task.task_type,
                            status="deferred",
                            payload={"autonomous_task_id": governed.get("task_id")},
                        )
                        continue
                    self._execute_autonomous_task(
                        leased, run_ref, artifact_dir, config, summary
                    )
                return drained

            def dispatch_cycle() -> dict[str, Any]:
                summary["iterations"] += 1
                scheduled = self.scheduler.schedule_cycle(run_ref, config)
                return {"scheduled": len(scheduled), "drained": drain_queue()}

            dispatch_interval = max(0.001, float(config.sleep_seconds))
            live_scheduler.add_job(
                "heartbeat",
                self.live_heartbeat.pulse,
                interval_seconds=5.0,
                priority=0,
                jitter_seconds=0.1,
                run_immediately=True,
            )
            live_scheduler.add_job(
                "dispatch",
                dispatch_cycle,
                interval_seconds=dispatch_interval,
                priority=20,
                jitter_seconds=min(1.0, dispatch_interval * 0.05),
                run_immediately=True,
            )

            target_iterations = max(1, int(config.max_iterations))
            while summary["iterations"] < target_iterations:
                if self.stop_file.exists():
                    summary["stop_requested"] = True
                    break
                live_scheduler.execute_due()
                if config.once:
                    break
                if summary["iterations"] < target_iterations:
                    wake_reason = live_scheduler.wait(maximum_seconds=5.0)
                    if wake_reason == "event":
                        drain_queue()
            summary["live_scheduler"] = live_scheduler.snapshot()
            summary["heartbeat"] = self.live_heartbeat.snapshot()
            summary["autonomous_tasks_governed"] = True
            status = (
                "completed" if not summary.get("errors") else "completed_with_errors"
            )
            self.store.finish_worker_run(run_ref, status, summary)
            self.store.set_state(
                "workers",
                {
                    "status": status,
                    "last_run_ref": run_ref,
                    "finished_at": utc_now(),
                    "summary": summary,
                },
            )
            (artifact_dir / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return {
                "status": status,
                "run_ref": run_ref,
                "artifact_dir": str(artifact_dir),
                **summary,
            }
        except WORKER_OPERATION_ERRORS as exc:
            record_internal_error(
                "worker_loop.run",
                exc,
                run_id=run_ref,
                payload={
                    "module": __name__,
                    "function": "run",
                    "operation": "worker_loop_main",
                },
                db_path=self.db_path,
            )
            summary["errors"].append(str(exc))
            self.store.finish_worker_run(run_ref, "failed", summary, error=str(exc))
            self.store.set_state(
                "workers",
                {
                    "status": "failed",
                    "last_run_ref": run_ref,
                    "error": str(exc),
                    "finished_at": utc_now(),
                },
            )
            return {
                "status": "failed",
                "run_ref": run_ref,
                "artifact_dir": str(artifact_dir),
                "error": str(exc),
                **summary,
            }
        finally:
            try:
                self.lock_file.unlink()
            except FileNotFoundError:
                pass

    def _execute_autonomous_task(
        self,
        leased: dict[str, Any],
        run_ref: str,
        artifact_dir: Path,
        config: WorkerRunConfig,
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        """Ejecuta una tarea solo después de adquirir su lease v2."""
        autonomous_task_id = str(leased["task_id"])
        lease_generation = int(leased["lease_generation"])
        payload = dict(leased.get("payload") or {})
        legacy_id = payload.pop("_legacy_task_id", None)
        canonical_artifacts = CanonicalTaskArtifacts(artifact_dir, autonomous_task_id)
        staging_path = canonical_artifacts.staging_path()
        task = WorkerTask(
            # v2 is the only execution identity; legacy_id is mirror metadata.
            id=None,
            task_type=str(leased["task_type"]),
            payload=payload,
            priority=int(leased.get("priority") or 50),
        )
        if not self.autonomous_tasks.start(
            autonomous_task_id, run_ref, lease_generation
        ):
            result = {"status": "error", "error": "autonomous_lease_lost"}
        else:
            heartbeat = LeaseHeartbeat(
                self.autonomous_tasks,
                autonomous_task_id,
                run_ref,
                lease_generation,
                max(60, int(config.task_timeout * 2)),
            )
            result = self._execute_task(
                task,
                run_ref,
                artifact_dir,
                config,
                lease_heartbeat=heartbeat,
                task_artifact_dir=staging_path,
            )
        provisional_ref = str(staging_path / "result.json")
        try:
            execution = self._canonical_execution_result(result, provisional_ref)
        except ValueError as exc:
            execution = ExecutionResult(
                status="failed",
                executed=True,
                retryable=False,
                error_code="unknown_handler_status",
                message=str(exc),
                artifacts=[provisional_ref] if Path(provisional_ref).exists() else [],
                evidence=[provisional_ref] if Path(provisional_ref).exists() else [],
            )
            result = {
                **result,
                "status": "error",
                "error": str(exc),
                "error_code": "unknown_handler_status",
            }

        final_result_ref = str(canonical_artifacts.path / "result.json")
        execution.artifacts = [final_result_ref]
        execution.evidence = [final_result_ref]
        if execution.effect_receipt is not None:
            execution.effect_receipt.evidence_refs = [final_result_ref]
        canonical_artifacts.finalize(
                task=leased,
                execution=execution.model_dump(mode="json"),
                result=result,
                worker_id=run_ref,
                lease_generation=lease_generation,
                payload_hash=str(leased["payload_hash"]),
                status=execution.status,
                target_path=staging_path,
            )
        result_ref = final_result_ref
        if execution.status == "completed":
            transitioned = AtomicCompletionCoordinator(self.autonomous_tasks).complete(
                task_id=autonomous_task_id,
                worker_id=run_ref,
                lease_generation=lease_generation,
                artifacts=canonical_artifacts,
                staging_path=staging_path,
            )
        else:
            try:
                canonical_artifacts.publish(staging_path)
            except OSError:
                transitioned = False
            else:
                transitioned = self._persist_execution_result(
                    autonomous_task_id,
                    run_ref,
                    lease_generation,
                    execution,
                    result_ref,
                )
        if not transitioned:
            execution = ExecutionResult(
                status="lease_lost",
                executed=True,
                retryable=True,
                error_code="terminal_transition_rejected",
                message="El lease dejó de pertenecer al worker antes del cierre",
                artifacts=[result_ref] if Path(result_ref).exists() else [],
                evidence=[],
            )
            result = {
                **result,
                "status": "lease_lost",
                "error": execution.message,
            }

        if execution.status == "blocked":
            summary["tasks_blocked"] += 1
        elif execution.status in {"failed", "dead_letter", "timeout", "lease_lost"}:
            summary["errors"].append(result.get("error") or "task_failed")
        elif execution.status == "completed":
            summary["tasks_completed"] += 1
        result["execution_result"] = execution.model_dump(mode="json")
        if legacy_id is not None:
            canonical = self.autonomous_tasks.get(autonomous_task_id) or {}
            terminal_status = str(canonical.get("status") or "")
            if terminal_status in {
                "completed",
                "blocked",
                "skipped",
                "dry_run",
                "observed",
                "cancelled",
                "failed",
                "dead_letter",
                "timeout",
                "lease_lost",
            }:
                self.store.mirror_v2_terminal(
                    int(legacy_id),
                    autonomous_task_id,
                    terminal_status,
                    result,
                    run_ref=run_ref,
                )
        return result

    @staticmethod
    def _canonical_execution_result(
        result: dict[str, Any], result_ref: str
    ) -> ExecutionResult:
        raw_status = str(result.get("status") or "").strip()
        evidence = [result_ref] if Path(result_ref).exists() else []
        message = str(result.get("reason") or result.get("message") or "")
        resource_usage = dict(result.get("resource_usage") or {})
        if raw_status in {"blocked"}:
            return ExecutionResult(status="blocked", executed=False, message=message)
        if raw_status == "skipped":
            return ExecutionResult(status="skipped", executed=False, message=message)
        if raw_status == "dry_run":
            return ExecutionResult(status="dry_run", executed=False, message=message)
        if raw_status in {"observed", "no_target", "no_evidence", "needs_research"}:
            return ExecutionResult(status="observed", executed=False, message=message)
        if raw_status in {"error", "failed"}:
            return ExecutionResult(
                status="failed",
                executed=True,
                retryable=True,
                error_code=str(result.get("error_code") or "handler_failed"),
                message=str(result.get("error") or message),
                artifacts=evidence,
                evidence=evidence,
                resource_usage=resource_usage,
            )
        if raw_status == "timeout":
            return ExecutionResult(
                status="timeout",
                executed=True,
                retryable=True,
                error_code="task_timeout",
                message=message,
                artifacts=evidence,
                evidence=evidence,
                resource_usage=resource_usage,
            )
        success = {"ok", "completed", "candidate_created", "consolidated", "lesson_prepared"}
        if raw_status not in success:
            raise ValueError(f"unknown_handler_status:{raw_status or '<empty>'}")
        effect_applied = raw_status in {"candidate_created", "consolidated", "lesson_prepared"}
        raw_receipt = result.get("effect_receipt")
        if raw_receipt:
            receipt = EffectReceipt.model_validate(raw_receipt)
        elif not effect_applied and evidence:
            receipt = EffectReceipt(
                action="observe",
                target=str(result.get("task_type") or "governed_handler"),
                execution={"handler_status": raw_status},
                postcondition={"passed": True, "result_artifact_exists": True},
                verified=True,
                verifier="result_artifact_verifier",
                evidence_refs=evidence,
            )
        else:
            return ExecutionResult(
                status="failed",
                executed=True,
                retryable=False,
                error_code="verified_effect_receipt_missing",
                message="El handler afirmó un efecto sin recibo verificable",
                artifacts=evidence,
                evidence=evidence,
                resource_usage=resource_usage,
            )
        return ExecutionResult(
            status="completed",
            executed=True,
            effect_applied=effect_applied,
            artifacts=evidence,
            evidence=evidence,
            resource_usage=resource_usage,
            observation_justification=None if evidence else "pure_observation_without_artifact",
            postconditions={"effect_expected": effect_applied},
            message=message,
            effect_receipt=receipt,
        )

    def _persist_execution_result(
        self,
        task_id: str,
        worker_id: str,
        lease_generation: int,
        execution: ExecutionResult,
        result_ref: str,
    ) -> bool:
        reason = execution.message or execution.error_code or execution.status
        if execution.status == "completed":
            return self.autonomous_tasks.complete(
                task_id, worker_id, lease_generation, result_ref
            )
        if execution.status == "blocked":
            return self.autonomous_tasks.block(task_id, worker_id, lease_generation, reason)
        if execution.status == "skipped":
            return self.autonomous_tasks.skip(task_id, worker_id, lease_generation, reason)
        if execution.status == "dry_run":
            return self.autonomous_tasks.mark_dry_run(
                task_id, worker_id, lease_generation, reason
            )
        if execution.status == "observed":
            return self.autonomous_tasks.mark_observed(
                task_id, worker_id, lease_generation, reason
            )
        if execution.status == "cancelled":
            return self.autonomous_tasks.cancel(task_id, worker_id, lease_generation, reason)
        if execution.status == "deferred":
            return self.autonomous_tasks.defer(task_id, worker_id, lease_generation, reason)
        if execution.status == "timeout":
            return self.autonomous_tasks.mark_timeout(
                task_id,
                worker_id,
                lease_generation,
                reason,
                retryable=execution.retryable,
            )
        if execution.status == "lease_lost":
            return self.autonomous_tasks.mark_lease_lost(
                task_id, worker_id, lease_generation, reason
            )
        if execution.status in {"failed", "dead_letter"}:
            failed = self.autonomous_tasks.fail(
                task_id, worker_id, lease_generation, reason
            )
            return failed.get("status") != "not_owner"
        raise ValueError(f"unknown_execution_status:{execution.status}")

    def request_stop(self) -> dict[str, Any]:
        self.stop_file.write_text(utc_now(), encoding="utf-8")
        self.store.set_state(
            "workers",
            {
                "status": "stop_requested",
                "stop_file": str(self.stop_file),
                "at": utc_now(),
            },
        )
        return {"status": "stop_requested", "stop_file": str(self.stop_file)}

    def clear_stop(self) -> None:
        try:
            self.stop_file.unlink()
        except FileNotFoundError:
            pass

    def _execute_task(
        self,
        task: WorkerTask,
        run_ref: str,
        artifact_dir: Path,
        config: WorkerRunConfig,
        *,
        lease_heartbeat: LeaseHeartbeat | None = None,
        task_artifact_dir: Path | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        resource_collector = ResourceMeasurementCollector()
        cancellation = CancellationToken(lambda: self.stop_file.exists())
        cancellation.checkpoint()
        goal_task = bool(task.payload.get("goal_id"))
        if not goal_task and self.adaptive_scheduler.should_skip_task(task.task_type):
            result: dict[str, Any] = {
                "status": "skipped",
                "reason": "adaptive_interval_not_elapsed",
                "task_type": task.task_type,
            }
            self.store.finish_task(
                task.id or 0, "skipped", result, "approved", run_ref=run_ref
            )
            return result
        blood = check_ollama_blood()
        blood_policy = ollama_blood_policy("worker_cycle", blood)
        safety = self._safety_for_task(task, run_ref)
        task_dir = task_artifact_dir or artifact_dir / f"task-{task.id}-{task.task_type}"
        task_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(task.payload, dict):
            task.payload.setdefault("ollama_blood", blood)
        base = {
            "task": task.to_dict(),
            "safety": safety.to_dict(),
            "dry_run": config.dry_run,
            "started_at": utc_now(),
        }
        (task_dir / "input.json").write_text(
            json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        if (
            blood_policy.get("degraded")
            and task.task_type not in self.READ_ONLY_TASKS_WITHOUT_BLOOD
        ):
            result = {
                "status": "blocked",
                "reason": "Ollama Blood no disponible; worker limitado a observe/read-only.",
                "ollama_blood_status": blood.get("status"),
                "model_used": blood.get("reasoning_model"),
                "degraded_mode": True,
                "cognitive_blood_active": False,
            }
            self.store.finish_task(
                task.id or 0, "blocked", result, safety.status, run_ref=run_ref
            )
            self.store.record_event(
                "task_blocked_no_blood",
                result["reason"],
                run_ref=run_ref,
                task_id=task.id,
                task_type=task.task_type,
                status="blocked",
                payload=result,
            )
        elif safety.status == "blocked" or safety.human_approval_required:
            result = {
                "status": "blocked",
                "reason": safety.reason,
                "safety_status": safety.status,
            }
            self.store.finish_task(
                task.id or 0, "blocked", result, safety.status, run_ref=run_ref
            )
            self.store.record_event(
                "task_blocked",
                safety.reason,
                run_ref=run_ref,
                task_id=task.id,
                task_type=task.task_type,
                status="blocked",
                payload=result,
            )
        elif config.dry_run:
            result = {
                "status": "dry_run",
                "task_type": task.task_type,
                "would_execute": True,
            }
            self.store.finish_task(
                task.id or 0, "completed", result, safety.status, run_ref=run_ref
            )
        else:
            try:
                handlers: dict[
                    str,
                    Callable[[WorkerTask, str, Path, WorkerRunConfig], dict[str, Any]],
                ] = {
                    "pulse_check": self._pulse_check,
                    "pending_learning_review": self._pending_learning_review,
                    "semantic_memory_governance": self._semantic_memory_governance,
                    "neuron_candidate_formation": self._neuron_candidate_formation,
                    "experimental_neuron_activity": self._experimental_neuron_activity,
                    "neuron_autopromotion": self._neuron_autopromotion,
                    "federation_inbox_review": self._federation_inbox_review,
                    "memory_consolidation_review": self._memory_consolidation_review,
                    "stable_consolidation_review": self._stable_consolidation_review,
                    "system_debt_scan": self._system_debt_scan,
                    "bodega_global_review": self._bodega_global_review,
                    "goal_research": self._goal_research,
                    "goal_safe_command": self._goal_safe_command,
                    "research_curriculum": self._research_curriculum,
                    "goal_install": self._goal_install,
                    "goal_lora_train": self._goal_lora_train,
                    "encrypted_backup": self._encrypted_backup,
                    "neuron_education_cycle": self._neuron_education_cycle,
                }
                outcome = self.task_executor.execute_callable(
                    handlers[task.task_type],
                    args=(task, run_ref, task_dir, config),
                    timeout_seconds=config.task_timeout,
                    artifact_dir=task_dir,
                    heartbeat=lease_heartbeat.renew if lease_heartbeat else None,
                    heartbeat_interval_seconds=(
                        lease_heartbeat.interval_seconds if lease_heartbeat else 15.0
                    ),
                    cancellation_check=lambda: cancellation.cancelled,
                )
                if outcome.status == "timeout":
                    result = {
                        "status": "timeout",
                        "error": outcome.error,
                        "timeout": config.task_timeout,
                        "termination_signal": outcome.termination_signal,
                        "quarantine_ref": outcome.quarantine_ref,
                        "stdout_ref": outcome.stdout_ref,
                        "stderr_ref": outcome.stderr_ref,
                    }
                elif outcome.status == "cancelled":
                    result = {"status": "cancelled", "reason": outcome.error}
                elif outcome.status == "lease_lost":
                    result = {
                        "status": "lease_lost",
                        "error": outcome.error,
                        "termination_signal": outcome.termination_signal,
                        "quarantine_ref": outcome.quarantine_ref,
                    }
                elif outcome.status == "failed":
                    result = {
                        "status": "error",
                        "error": outcome.error or "governed_child_failed",
                        "exit_code": outcome.exit_code,
                        "stdout_ref": outcome.stdout_ref,
                        "stderr_ref": outcome.stderr_ref,
                    }
                else:
                    result = outcome.result
                result_status = str(result.get("status") or "completed")
                if result_status in {
                    "ok",
                    "completed",
                    "candidate_created",
                    "consolidated",
                    "lesson_prepared",
                }:
                    persisted_status = "completed"
                elif result_status in {
                    "observed",
                    "no_target",
                    "no_evidence",
                    "needs_research",
                }:
                    persisted_status = "observed"
                elif result_status in {
                    "blocked",
                    "skipped",
                    "dry_run",
                    "cancelled",
                    "failed",
                    "timeout",
                    "lease_lost",
                }:
                    persisted_status = (
                        "failed" if result_status == "error" else result_status
                    )
                elif result_status == "error":
                    persisted_status = "failed"
                else:
                    raise ValueError(f"unknown_handler_status:{result_status}")
                self.store.finish_task(
                    task.id or 0,
                    persisted_status,
                    result,
                    safety.status,
                    run_ref=run_ref,
                )
                self.store.record_event(
                    f"task_{persisted_status}",
                    f"{task.task_type}: {persisted_status}",
                    run_ref=run_ref,
                    task_id=task.id,
                    task_type=task.task_type,
                    payload=result,
                )
                if task.payload.get("goal_id"):
                    from triade.core.goal_orchestrator import GoalOrchestrator

                    GoalOrchestrator(self.db_path).record_task_result(
                        task.payload, result
                    )
            except WORKER_OPERATION_ERRORS as exc:
                record_internal_error(
                    "worker_loop.execute_task",
                    exc,
                    run_id=run_ref,
                    task_id=task.id,
                    payload={
                        "module": __name__,
                        "function": "_execute_task",
                        "operation": "execute_worker_task_handler",
                        "task_type": task.task_type,
                    },
                    db_path=self.db_path,
                )
                result = {
                    "status": "error",
                    "task_type": task.task_type,
                    "error": str(exc),
                }
                self.store.finish_task(
                    task.id or 0,
                    "failed",
                    result,
                    safety.status,
                    error=str(exc),
                    run_ref=run_ref,
                )
                self.store.record_event(
                    "task_failed",
                    str(exc),
                    run_ref=run_ref,
                    task_id=task.id,
                    task_type=task.task_type,
                    status="error",
                    payload=result,
                )
        result["ollama_blood_status"] = blood.get("status")
        result["model_used"] = blood.get("reasoning_model")
        result["degraded_mode"] = bool(blood_policy.get("degraded"))
        result["cognitive_blood_active"] = bool(blood.get("cognitive_blood_active"))
        result["elapsed"] = round(time.monotonic() - started, 4)
        self.adaptive_scheduler.record_task_execution(
            task.task_type,
            result["elapsed"] * 1000,
            str(result.get("status")) not in {"error", "failed", "blocked"},
            run_ref=run_ref,
        )
        resource_usage = resource_collector.finish()
        result["resource_usage"] = resource_usage.to_dict()
        self.resource_ledger.record_usage(
            task_id=str(task.id) if task.id is not None else None,
            worker_id=run_ref,
            neuron_id=str(
                task.payload.get("neuron_id")
                or task.payload.get("related_neuron_id")
                or ""
            )
            or None,
            usage=resource_usage,
            model=str(result.get("model_used") or "") or None,
            success=str(result.get("status")) not in {"error", "failed", "blocked"},
            task_class=self.adaptive_scheduler.task_class(task.task_type),
        )
        task_dir.mkdir(parents=True, exist_ok=True)
        from triade.runtime.task_artifacts import AtomicArtifactWriter

        AtomicArtifactWriter.write_json(task_dir / "result.json", result)
        return result

    def _research_curriculum(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        """Investiga una laguna real; la evidencia queda candidata, nunca estable."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT n.id, n.name, n.domain, COUNT(na.id) AS evidence_count
                   FROM neurons n LEFT JOIN neuron_activity na ON na.neuron_id=n.id
                   WHERE n.status IN ('experimental','candidate','candidate_reviewable')
                   GROUP BY n.id ORDER BY evidence_count ASC, n.id ASC LIMIT 1"""
            ).fetchone()
        if row is None:
            return {"status": "no_evidence", "reason": "no_neuronal_gap"}
        domain_value = str(row["domain"] or "general")
        domain_queries = {
            "vision_image_understanding": "visión artificial procesamiento de imágenes OpenCV Pillow",
            "code_repair": "ingeniería de software depuración pruebas reproducibles",
            "code_repair_build_tests": "ingeniería de software código depuración pruebas testing pytest unittest",
            "system_governance": "gobernanza de sistemas software auditoría trazabilidad",
        }
        clean_domain = domain_queries.get(domain_value, domain_value.replace("_", " "))
        clean_name = str(row["name"] or "").replace("neurona-", "").replace("-", " ")
        delegated = WorkerTask(
            task_type="goal_research",
            payload={
                "request": f"{clean_domain} {clean_name} documentación técnica fundamentos",
                "related_neuron_id": int(row["id"]),
                "curriculum": True,
            },
        )
        result = self._goal_research(delegated, run_ref, task_dir, config)
        result["curriculum_gap"] = dict(row)
        return result

    def _goal_install(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        from triade.training.installer import IsolatedInstaller

        return IsolatedInstaller(self.db_path).install(
            str(task.payload.get("package") or ""),
            goal_id=str(task.payload.get("goal_id") or run_ref),
            approved=bool(task.payload.get("human_approved")),
            approved_by=str(task.payload.get("approved_by") or ""),
        )

    def _goal_lora_train(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        from triade.training.governed_lora import GovernedLoraJobRunner

        return GovernedLoraJobRunner(self.db_path).run(task.payload)

    def _encrypted_backup(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        from triade.memory.encrypted_backup import EncryptedBackup

        backup = EncryptedBackup(self.db_path)
        created = backup.create()
        verified = backup.verify(Path("artifacts/backups") / created["file"])
        if verified.get("status") != "ok":
            return {
                "status": "error",
                "reason": "backup_verification_failed",
                "verification": verified,
            }
        return {
            "status": "completed",
            "backup": created,
            "verification": verified,
            "retention": backup.enforce_retention(),
        }

    def _neuron_education_cycle(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        from triade.neurons import NeuronEducationCycle

        result = NeuronEducationCycle(self.db_path).run_once()
        result["run_ref"] = run_ref
        result["stable_memory_written"] = False
        result["stable_neuron_promotion"] = False
        return result

    def _safety_for_task(self, task: WorkerTask, run_ref: str):
        signals = SignalPacket(
            run_id=run_ref,
            intent="worker",
            tone="operational",
            urgency="low",
            risk="low",
            pv7={},
            notes=[task.task_type],
        )
        plan = PlanPacket(
            run_id=run_ref,
            goal=f"Ejecutar worker task {task.task_type}",
            steps=["safe_background_cycle"],
            tools=[],
        )
        memory = MemoryPacket(run_id=run_ref, semantic_recall={"enabled": False})
        crystal = CrystalPacket(run_id=run_ref, temporal_status="stable")
        return Safety().review(signals, plan, crystal=crystal, memory=memory)

    def _publish_qualia_experience(
        self,
        run_ref: str,
        task_type: str,
        neuron_type: str,
        observation: str,
        extracted_pattern: str = "",
        proposed_learning: str = "",
        confidence: float = 0.6,
        risk: str = "low",
        usefulness: float = 0.5,
        ingest_learning: bool | None = None,
    ) -> dict[str, Any] | None:
        try:
            bus = QualiaBus(db_path=self.db_path)
            exp = NeuronExperience(
                run_id=run_ref,
                neuron_id=f"worker:{task_type}",
                neuron_type=neuron_type,
                mission=f"Living Worker ejecutó {task_type}",
                source="living_worker",
                source_type="worker_task",
                observation=observation[:1000],
                extracted_pattern=extracted_pattern[:1000],
                proposed_learning=proposed_learning[:1000],
                confidence=confidence,
                risk=risk,
                usefulness=usefulness,
                evidence_refs=[f"worker:{run_ref}", f"task:{task_type}"],
            )
            # Telemetría Qualia no se convierte en aprendizaje por defecto.
            result = bus.publish_experience(
                exp,
                ingest_learning=False if ingest_learning is None else ingest_learning,
            )
            return {
                "published": True,
                "experience_id": exp.id,
                "state": result.get("state", {}).to_dict()
                if hasattr(result.get("state"), "to_dict")
                else result.get("state"),
            }
        except WORKER_OPERATION_ERRORS as exc:
            record_internal_error(
                "worker_loop.qualia_publish",
                exc,
                run_id=run_ref,
                payload={
                    "module": __name__,
                    "function": "_publish_qualia_experience",
                    "operation": "publish_worker_qualia_experience",
                    "task_type": task_type,
                },
                db_path=self.db_path,
            )
            return {"published": False, "error": str(exc)}

    def _pulse_check(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        from apps.services import build_system_pulse

        pulse = build_system_pulse(sync_relay=False)
        return {
            "status": "completed",
            "pulse": pulse,
            "policy": "local_only_no_external_relay_sync",
            "qualia": {
                "published": False,
                "reason": "heartbeat_is_telemetry_not_experience",
            },
        }

    def _pending_learning_review(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        pipe = LearningPipeline(db_path=self.db_path)
        sandbox = WorkerSandbox(task_dir)
        processed = []
        for candidate in pipe.list_candidates(status="candidate", limit=5):
            sb = sandbox.run(
                "validate_learning_candidate", candidate, timeout=config.task_timeout
            )
            if sb.get("identity_red_flag"):
                processed.append(
                    pipe.reject(
                        candidate["candidate_id"],
                        reason="worker sandbox detected identity_core risk",
                    )
                )
            else:
                processed.append(pipe.evaluate(candidate["candidate_id"]))
        for candidate in pipe.list_candidates(status="evaluated", limit=5):
            verified = pipe.verify(candidate["candidate_id"])
            processed.append(verified)
        qualia = (
            self._publish_qualia_experience(
                run_ref,
                "pending_learning_review",
                "worker_learning",
                f"Worker realizó {len(processed)} transiciones de aprendizaje.",
                proposed_learning="Transiciones candidate→evaluated→internally_checked registradas.",
                ingest_learning=False,
            )
            if processed
            else {"published": False, "reason": "no_state_transition"}
        )
        return {
            "status": "completed",
            "processed_count": len(processed),
            "processed": processed,
            "stable_memory_written": False,
            "qualia": qualia,
        }

    def _semantic_memory_governance(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        governance = SemanticMemoryGovernance(db_path=self.db_path).doctor()
        qualia = self._publish_qualia_experience(
            run_ref,
            "semantic_memory_governance",
            "worker_governance",
            f"Gobernanza semántica ejecutada: {governance.get('status', 'unknown')}.",
            extracted_pattern=str(governance),
        )
        return {"status": "completed", "governance": governance, "qualia": qualia}

    def _neuron_candidate_formation(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        pulse = {
            "status": "unknown",
            "summary": "worker background scan",
            "federation": {"android_native_online": 0, "android_llm_hosts": 0},
        }
        raw = candidates_from_system_debt(pulse_summary=pulse)
        formed = form_candidates(raw)
        qualia = self._publish_qualia_experience(
            run_ref,
            "neuron_candidate_formation",
            "worker_formation",
            f"Formación de candidatos: {len(raw)} raw → {len(formed)} formados.",
            extracted_pattern=str([c.get("name", "") for c in formed[:5]]),
        )
        return {
            "status": "completed",
            "raw_count": len(raw),
            "formed_count": len(formed),
            "candidates": formed,
            "qualia": qualia,
        }

    def _experimental_neuron_activity(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        from triade.core.neuron_mission_selector import select_relevant_missions
        from triade.core.neuron_missions import NeuronMissionStore

        mission_id = task.payload.get("mission_id")
        if mission_id is not None:
            store = NeuronMissionStore(db_path=self.db_path)
            mission = store.get_mission(int(mission_id))
            selection = select_relevant_missions(
                user_input=str(
                    task.payload.get("query") or task.payload.get("user_input") or ""
                ),
                domain=str(
                    task.payload.get("domain")
                    or (mission.domain if mission else "")
                    or ""
                ),
                memory_context=task.payload.get("memory_context")
                or task.payload.get("context")
                or {},
                db_path=self.db_path,
                limit=5,
            )
            relevant_ids = {
                int(item["id"])
                for item in (selection.get("selected") or [])
                if item.get("id") is not None
            }
            if mission is None:
                blocked = {
                    "status": "blocked",
                    "decision": "mission_not_found",
                    "mission_id": int(mission_id),
                    "mission_selection": selection,
                    "mission_selection_policy": selection.get("policy", {}),
                    "relevant_missions": selection.get("selected", []),
                    "stable_memory_written": False,
                }
                qualia = self._publish_qualia_experience(
                    run_ref,
                    "experimental_neuron_activity",
                    "worker_neuron_mission_blocked",
                    f"Misión neuronal {mission_id} no encontrada; ejecución bloqueada.",
                    extracted_pattern=str(
                        {"mission_id": mission_id, "decision": "mission_not_found"}
                    ),
                    proposed_learning="No ejecutar misiones neuronales inexistentes.",
                    confidence=0.1,
                    usefulness=0.1,
                    ingest_learning=False,
                )
                return {**blocked, "qualia": qualia}
            if int(mission_id) not in relevant_ids:
                blocked = {
                    "status": "blocked",
                    "decision": "blocked_by_relevance",
                    "mission_id": int(mission_id),
                    "mission_title": mission.title,
                    "mission_domain": mission.domain,
                    "mission_selection": selection,
                    "mission_selection_policy": selection.get("policy", {}),
                    "relevant_missions": selection.get("selected", []),
                    "stable_memory_written": False,
                }
                qualia = self._publish_qualia_experience(
                    run_ref,
                    "experimental_neuron_activity",
                    "worker_neuron_mission_blocked",
                    f"Misión neuronal {mission_id} bloqueada por relevancia insuficiente.",
                    extracted_pattern=str(
                        {
                            "mission_id": mission_id,
                            "decision": "blocked_by_relevance",
                            "selected_count": selection.get("count", 0),
                        }
                    ),
                    proposed_learning="No ejecutar misiones neuronales irrelevantes.",
                    confidence=0.2,
                    usefulness=0.2,
                    ingest_learning=False,
                )
                return {**blocked, "qualia": qualia}
            mission_result = NeuronMissionExecutor(db_path=self.db_path).execute(
                mission_id=int(mission_id),
                run_ref=run_ref,
                task_payload=task.payload,
                task_dir=task_dir,
                config=config,
            )
            qualia = self._publish_qualia_experience(
                run_ref,
                "experimental_neuron_activity",
                "worker_neuron_mission",
                str(
                    mission_result.get("observation")
                    or mission_result.get("decision")
                    or "Misión neuronal ejecutada."
                ),
                extracted_pattern=str(
                    {
                        "mission_id": mission_result.get("mission_id"),
                        "cycle_id": mission_result.get("cycle_id"),
                        "evidence_id": mission_result.get("evidence_id"),
                        "score_id": mission_result.get("score_id"),
                        "decision": mission_result.get("decision"),
                    }
                ),
                proposed_learning=str(mission_result.get("proposed_learning") or "")[
                    :1000
                ],
                confidence=float(mission_result.get("composite_score") or 0.6),
                usefulness=float(mission_result.get("composite_score") or 0.5),
                ingest_learning=False,
            )
            return {
                **mission_result,
                "stable_memory_written": False,
                "qualia": qualia,
                "mission_selection": selection,
                "mission_selection_policy": selection.get("policy", {}),
                "relevant_missions": selection.get("selected", []),
            }

        signals = SignalPacket(
            run_id=run_ref,
            intent="worker",
            tone="operational",
            urgency="low",
            risk="low",
            notes=["background"],
        )
        query = str(
            task.payload.get("query") or "pulso memoria federacion modelo estado worker"
        )
        domain = str(task.payload.get("domain") or "")
        selection = select_relevant_missions(
            user_input=query,
            domain=domain or None,
            db_path=self.db_path,
            limit=5,
        )
        relevant = selection.get("selected") or []
        first_mission_id = relevant[0]["id"] if relevant else None
        if first_mission_id is not None:
            mission_result = NeuronMissionExecutor(db_path=self.db_path).execute(
                mission_id=int(first_mission_id),
                run_ref=run_ref,
                task_payload={
                    **task.payload,
                    "selected_by_relevance": True,
                    "selection_result": selection,
                },
                task_dir=task_dir,
                config=config,
            )
            qualia = self._publish_qualia_experience(
                run_ref,
                "experimental_neuron_activity",
                "worker_neuron_relevant_mission",
                str(
                    mission_result.get("observation")
                    or mission_result.get("decision")
                    or "Misión neuronal ejecutada por relevancia."
                ),
                extracted_pattern=str(
                    {
                        "mission_id": mission_result.get("mission_id"),
                        "cycle_id": mission_result.get("cycle_id"),
                        "evidence_id": mission_result.get("evidence_id"),
                        "score_id": mission_result.get("score_id"),
                        "decision": mission_result.get("decision"),
                        "relevance_count": selection.get("count"),
                    }
                ),
                proposed_learning=str(mission_result.get("proposed_learning") or "")[
                    :1000
                ],
                confidence=float(mission_result.get("composite_score") or 0.6),
                usefulness=float(mission_result.get("composite_score") or 0.5),
                ingest_learning=False,
            )
            return {
                **mission_result,
                "stable_memory_written": False,
                "qualia": qualia,
                "mission_selection": selection,
                "mission_selection_policy": selection.get("policy", {}),
                "relevant_missions": selection.get("selected", []),
            }

        activity = run_experimental_neurons(
            db_path=str(self.db_path),
            user_input="pulso memoria federacion modelo estado worker",
            context={"domain": "system_governance", "active_neuron": "living-workers"},
            signals=signals,
            edge_usage={
                "used_edge": False,
                "accepted": False,
                "keywords": ["pulso", "memoria", "federacion"],
            },
            system_events=[],
        )
        ids = NeuronActivityStore(db_path=self.db_path).record_run_activity(
            run_ref, activity
        )
        activity["db_activity_ids"] = ids
        qualia = self._publish_qualia_experience(
            run_ref,
            "experimental_neuron_activity",
            "worker_neuron_activity",
            f"Actividad experimental: {len(ids)} registros de actividad.",
            extracted_pattern=str(activity.get("summary", "")),
        )
        return {"status": "completed", "activity": activity, "qualia": qualia}

    def _neuron_autopromotion(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        events = NeuronAutopromoter(db_path=self.db_path).promote()
        qualia = (
            self._publish_qualia_experience(
                run_ref,
                "neuron_autopromotion",
                "worker_autopromotion",
                f"Promoción gobernada produjo {len(events)} transiciones.",
                extracted_pattern=str(events[:3]),
                ingest_learning=False,
            )
            if events
            else {"published": False, "reason": "no_state_transition"}
        )
        return {
            "status": "completed",
            "events": events,
            "stable_promotion_requires_readiness": True,
            "qualia": qualia,
        }

    def _federation_inbox_review(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        federation = Federation(db_path=self.db_path)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT exchange_id, source_node_id, target_node_id, exchange_type, risk_level, safety_status, decision, reason, created_at FROM federated_exchange_log ORDER BY id DESC LIMIT 10"
            ).fetchall()
        return {
            "status": "completed",
            "doctor": federation.doctor(),
            "recent_exchanges": [dict(row) for row in rows],
            "external_network": False,
        }

    def _memory_consolidation_review(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        pipe = LearningPipeline(db_path=self.db_path)
        SemanticMemoryStore(db_path=self.db_path)
        SemanticMemoryGovernance(db_path=self.db_path)
        sandbox = WorkerSandbox(task_dir)
        promoted = []
        for candidate in pipe.list_candidates(status="internally_checked", limit=5):
            sb = sandbox.run(
                "analyze_memory_candidate", candidate, timeout=config.task_timeout
            )
            if sb.get("status") != "ok" or not candidate.get("source_ref"):
                continue
            promoted.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "action": "awaiting_real_run_evidence",
                }
            )
        return {
            "status": "completed",
            "run_tracking_updates": promoted,
            "stable_memory_written": False,
        }

    def _stable_consolidation_review(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        """Revisa candidatos con evidencia suficiente y solo entonces permite consolidar."""
        pipe = LearningPipeline(db_path=self.db_path)
        sandbox = WorkerSandbox(task_dir)
        consolidated = []
        rejected = []
        for candidate in pipe.list_candidates(status="validated_in_runs", limit=5):
            sb = sandbox.run(
                "analyze_memory_candidate", candidate, timeout=config.task_timeout
            )
            if sb.get("status") != "ok" or not candidate.get("source_ref"):
                rejected.append(
                    {
                        "candidate_id": candidate.get("candidate_id"),
                        "reason": "sandbox_check_failed",
                    }
                )
                continue
            try:
                result = pipe.consolidate(
                    candidate["candidate_id"],
                    approved_by=f"worker-stable-review:{run_ref}",
                )
                consolidated.append(
                    {
                        "candidate_id": candidate.get("candidate_id"),
                        "document_id": result.get("semantic_document_id"),
                        "status": "consolidated",
                    }
                )
            except ValueError as exc:
                rejected.append(
                    {"candidate_id": candidate.get("candidate_id"), "reason": str(exc)}
                )
        qualia = self._publish_qualia_experience(
            run_ref,
            "stable_consolidation_review",
            "worker_stable_review",
            f"Revisión estable: {len(consolidated)} consolidados, {len(rejected)} rechazados.",
            proposed_learning="Solo consolidar cuando evidencia de uso acumulada demuestra valor real.",
        )
        return {
            "status": "completed",
            "consolidated": consolidated,
            "rejected": rejected,
            "stable_memory_written": bool(consolidated),
            "qualia": qualia,
        }

    def _system_debt_scan(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        content = "Worker detectó deuda operacional: mantener vivo el ciclo observar→evaluar→sandbox→memoria experimental→medición."
        qualia = self._publish_qualia_experience(
            run_ref,
            "system_debt_scan",
            "worker_debt",
            "Deuda operacional detectada: ciclo observar→evaluar→sandbox→memoria experimental→medición.",
            proposed_learning="Mantener vivo el ciclo de observación y evaluación continua.",
        )
        return {
            "status": "observed",
            "observation": content,
            "learning_candidate": None,
            "truth": "worker_self_observation_not_learning_evidence",
            "qualia": qualia,
        }

    def _bodega_global_review(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        """Revisa memoria reciente, learning_queue y stable_audit sin modificar identity_core.

        Produce un evento worker y experiencia Qualia. No consolida memoria
        automáticamente y no modifica identity_core.
        """
        from triade.core.bodega_global_context import build_bodega_global_context

        query = str(task.payload.get("query") or "revisión global de memoria")
        bodega_ctx = build_bodega_global_context(
            user_input=query,
            db_path=self.db_path,
            runs_dir=self.runs_dir,
            limit=10,
            semantic_recall_enabled=True,
        )

        episodes_count = len(bodega_ctx.get("recent_episodes") or [])
        learning = bodega_ctx.get("learning_context") or {}
        candidates_count = learning.get("candidates", 0)
        verified_count = learning.get("verified", 0)
        stable_audit = bodega_ctx.get("stable_audit_summary") or {}
        needs_review = stable_audit.get("stable_needs_review", 0)
        mem_conf = bodega_ctx.get("memory_confidence", "low")
        contradictions = bodega_ctx.get("contradictions") or []

        summary = (
            f"Revisión bodega global: confianza={mem_conf}, "
            f"episodios={episodes_count}, candidatos={candidates_count}, "
            f"verificados={verified_count}, stable_needs_review={needs_review}, "
            f"contradicciones={len(contradictions)}."
        )

        qualia = self._publish_qualia_experience(
            run_ref,
            "bodega_global_review",
            "worker_bodega_global",
            summary,
            extracted_pattern=str(
                {
                    "memory_confidence": mem_conf,
                    "episodes_count": episodes_count,
                    "candidates_count": candidates_count,
                    "verified_count": verified_count,
                    "stable_needs_review": needs_review,
                    "contradictions_count": len(contradictions),
                }
            )[:1000],
            proposed_learning="Mantener bodega global como base viva de contexto sin consolidar memoria automáticamente.",
        )

        return {
            "status": "completed",
            "memory_confidence": mem_conf,
            "episodes_count": episodes_count,
            "candidates_count": candidates_count,
            "verified_count": verified_count,
            "stable_needs_review": needs_review,
            "contradictions_count": len(contradictions),
            "stable_memory_written": False,
            "identity_core_modified": False,
            "qualia": qualia,
        }

    def _shell_execute(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        """Ejecuta un comando shell autónomo con gating de autonomía y audit.

        Payload esperado: {command_key, autonomy_level?, timeout?, working_dir?}
        El resultado se registra como evidencia para neuronas.
        """
        from triade.core.safe_shell import run_autonomous

        payload = task.payload if isinstance(task.payload, dict) else {}
        command_key = str(payload.get("command_key", ""))
        if not command_key:
            return {"status": "error", "error": "command_key requerido en payload."}

        autonomy_level = str(payload.get("autonomy_level", "observe_only"))
        timeout = int(payload.get("timeout", 60))
        working_dir = payload.get("working_dir")

        result = run_autonomous(
            command_key=command_key,
            timeout=timeout,
            autonomy_level=autonomy_level,
            source="worker",
            working_dir=working_dir,
        )

        # Registrar como evidencia si fue exitoso.
        if result.get("status") == "ok":
            try:
                from triade.services.event_bus import publish_event

                publish_event(
                    "shell_command_executed",
                    "worker_shell",
                    {
                        "command_key": command_key,
                        "returncode": result.get("returncode"),
                        "duration_ms": result.get("duration_ms"),
                        "stdout_preview": (result.get("stdout") or "")[:200],
                    },
                    db_path=self.db_path,
                    run_ref=run_ref,
                )
            except WORKER_OPERATION_ERRORS as exc:
                record_internal_error(
                    "worker_loop.shell_event",
                    exc,
                    run_id=run_ref,
                    task_id=task.id,
                    payload={
                        "module": __name__,
                        "function": "_shell_execute",
                        "operation": "publish_shell_execution_event",
                    },
                    db_path=self.db_path,
                )

        return result

    def _goal_safe_command(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        return self._shell_execute(task, run_ref, task_dir, config)

    def _goal_research(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        from triade.research import AutonomousResearchEngine

        request = str(task.payload.get("request") or "").strip()
        if not request:
            return {"status": "error", "error": "request requerido"}
        return AutonomousResearchEngine(self.db_path).research(
            request, trigger="goal_worker"
        )

    def _artifact_dir(self, run_ref: str) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return self.runs_dir / f"{stamp}-{run_ref[-8:]}"

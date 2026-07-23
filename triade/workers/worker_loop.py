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

from .contracts import WORKER_TASK_TYPES, WorkerRunConfig, WorkerTask, new_worker_run_id
from .neuron_mission_executor import NeuronMissionExecutor
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
    READ_ONLY_TASKS_WITHOUT_BLOOD = frozenset({"pulse_check", "pending_learning_review", "semantic_memory_governance", "federation_inbox_review", "bodega_global_review"})

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
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.stop_file.parent.mkdir(parents=True, exist_ok=True)
        if self.stop_file.exists():
            return {"status": "stopped", "stop_file": str(self.stop_file), "message": "Stop file presente antes de iniciar."}

        # Atomic lock: O_CREAT|O_EXCL evita carrera TOCTOU entre múltiples instancias.
        # Un PID numérico muerto identifica un lock huérfano recuperable.
        self._recover_stale_lock()
        try:
            fd = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            os.close(fd)
        except FileExistsError:
            return {"status": "locked", "lock_file": str(self.lock_file), "message": "Worker ya está en ejecución."}
        run_ref = new_worker_run_id()
        artifact_dir = self._artifact_dir(run_ref)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        blood = check_ollama_blood()
        blood_policy = ollama_blood_policy("worker_cycle", blood)
        from triade.services.event_bus import publish_event

        publish_event(
            "ollama_blood_checked",
            "worker_loop",
            {"status": blood.get("status"), "blood_pressure_score": blood.get("blood_pressure_score")},
            db_path=self.db_path,
            run_ref=run_ref,
        )
        publish_event(
            "ollama_blood_active" if blood_policy.get("allowed") and not blood_policy.get("degraded") else "ollama_blood_degraded",
            "worker_loop",
            {"status": blood.get("status"), "degraded_components": blood.get("degraded_components", [])},
            severity="info" if blood_policy.get("allowed") and not blood_policy.get("degraded") else "warning",
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
        }
        self.store.create_worker_run(run_ref, config, artifact_dir)
        self.store.set_state("workers", {"status": "running", "run_ref": run_ref, "started_at": utc_now(), "config": config.to_dict()})
        self.store.heartbeat_execution(run_ref, ttl_seconds=max(30.0, float(config.sleep_seconds) * 2.5))

        try:
            for iteration in range(max(1, int(config.max_iterations))):
                self.store.heartbeat_execution(run_ref, ttl_seconds=max(30.0, float(config.sleep_seconds) * 2.5))
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
            self.store.heartbeat_execution(run_ref, status=status)
            self.store.set_state("workers", {"status": status, "last_run_ref": run_ref, "finished_at": utc_now(), "summary": summary})
            (artifact_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"status": status, "run_ref": run_ref, "artifact_dir": str(artifact_dir), **summary}
        except Exception as exc:
            record_internal_error(
                "worker_loop.run",
                exc,
                run_id=run_ref,
                payload={"module": __name__, "function": "run", "operation": "worker_loop_main"},
                db_path=self.db_path,
            )
            summary["errors"].append(str(exc))
            self.store.finish_worker_run(run_ref, "failed", summary, error=str(exc))
            self.store.heartbeat_execution(run_ref, status="failed")
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

    def _recover_stale_lock(self) -> bool:
        if not self.lock_file.exists():
            return False
        try:
            owner_pid = int(self.lock_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return False
        try:
            os.kill(owner_pid, 0)
            return False
        except ProcessLookupError:
            try:
                self.lock_file.unlink()
                self.store.record_event(
                    "stale_worker_lock_recovered",
                    "Lock huérfano eliminado después de comprobar su PID.",
                    payload={"lock_file": str(self.lock_file), "owner_pid": owner_pid},
                )
                return True
            except FileNotFoundError:
                return False
        except PermissionError:
            return False

    def clear_stop(self) -> None:
        try:
            self.stop_file.unlink()
        except FileNotFoundError:
            pass

    def _execute_task(self, task: WorkerTask, run_ref: str, artifact_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
        started = time.monotonic()
        blood = check_ollama_blood()
        blood_policy = ollama_blood_policy("worker_cycle", blood)
        safety = self._safety_for_task(task, run_ref)
        task_dir = artifact_dir / f"task-{task.id}-{task.task_type}"
        task_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(task.payload, dict):
            task.payload.setdefault("ollama_blood", blood)
        base = {"task": task.to_dict(), "safety": safety.to_dict(), "dry_run": config.dry_run, "started_at": utc_now()}
        (task_dir / "input.json").write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")

        if blood_policy.get("degraded") and task.task_type not in self.READ_ONLY_TASKS_WITHOUT_BLOOD:
            result = {
                "status": "blocked",
                "reason": "Ollama Blood no disponible; worker limitado a observe/read-only.",
                "ollama_blood_status": blood.get("status"),
                "model_used": blood.get("reasoning_model"),
                "degraded_mode": True,
                "cognitive_blood_active": False,
            }
            self.store.finish_task(task.id or 0, "blocked", result, safety.status, run_ref=run_ref)
            self.store.record_event("task_blocked_no_blood", result["reason"], run_ref=run_ref, task_id=task.id, task_type=task.task_type, status="blocked", payload=result)
        elif safety.status == "blocked" or safety.human_approval_required:
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
                    "stable_consolidation_review": self._stable_consolidation_review,
                    "system_debt_scan": self._system_debt_scan,
                    "bodega_global_review": self._bodega_global_review,
                }
                result = handlers[task.task_type](task, run_ref, task_dir, config)
                if time.monotonic() - started > config.task_timeout:
                    raise TimeoutError(f"worker task timeout: {task.task_type}")
                self.store.finish_task(task.id or 0, result.get("status", "completed"), result, safety.status, run_ref=run_ref)
                self.store.record_event("task_completed", f"{task.task_type} completada", run_ref=run_ref, task_id=task.id, task_type=task.task_type, payload=result)
            except Exception as exc:
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
                result = {"status": "error", "task_type": task.task_type, "error": str(exc)}
                self.store.finish_task(task.id or 0, "failed", result, safety.status, error=str(exc), run_ref=run_ref)
                self.store.record_event("task_failed", str(exc), run_ref=run_ref, task_id=task.id, task_type=task.task_type, status="error", payload=result)
        result["ollama_blood_status"] = blood.get("status")
        result["model_used"] = blood.get("reasoning_model")
        result["degraded_mode"] = bool(blood_policy.get("degraded"))
        result["cognitive_blood_active"] = bool(blood.get("cognitive_blood_active"))
        result["elapsed"] = round(time.monotonic() - started, 4)
        (task_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def _safety_for_task(self, task: WorkerTask, run_ref: str):
        signals = SignalPacket(run_id=run_ref, intent="worker", tone="operational", urgency="low", risk="low", pv7={}, notes=[task.task_type])
        plan = PlanPacket(run_id=run_ref, goal=f"Ejecutar worker task {task.task_type}", steps=["safe_background_cycle"], tools=[])
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
            result = bus.publish_experience(exp, ingest_learning=bool(proposed_learning) if ingest_learning is None else ingest_learning)
            return {"published": True, "experience_id": exp.id, "state": result.get("state", {}).to_dict() if hasattr(result.get("state"), "to_dict") else result.get("state")}
        except Exception as exc:
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

    def _pulse_check(self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
        from apps.services import build_system_pulse
        pulse = build_system_pulse(sync_relay=False)
        qualia = self._publish_qualia_experience(
            run_ref,
            "pulse_check",
            "worker_pulse",
            "Worker ejecutó verificación de pulso local.",
            extracted_pattern=str({"status": pulse.get("status"), "mode": pulse.get("mode")})[:1000],
        )
        return {"status": "completed", "pulse": pulse, "policy": "local_only_no_external_relay_sync", "qualia": qualia}

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
            verified = pipe.verify(candidate["candidate_id"])
            processed.append(verified)
            if verified.get("status") == "verified" and verified.get("source_ref"):
                try:
                    processed.append(pipe.mark_used_in_run(
                        verified["candidate_id"],
                        run_ref,
                        outcome_score=0.80,
                    ))
                except ValueError as exc:
                    processed.append({"candidate_id": verified.get("candidate_id"), "action": "mark_used_skipped", "reason": str(exc)})
        qualia = self._publish_qualia_experience(
            run_ref, "pending_learning_review", "worker_learning",
            f"Worker revisó {len(processed)} candidatos de aprendizaje.",
            proposed_learning="Mantener ciclo de aprendizaje controlado: candidate→evaluated→verified.",
        )
        return {"status": "completed", "processed_count": len(processed), "processed": processed, "stable_memory_written": False, "qualia": qualia}

    def _semantic_memory_governance(self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
        governance = SemanticMemoryGovernance(db_path=self.db_path).doctor()
        qualia = self._publish_qualia_experience(
            run_ref, "semantic_memory_governance", "worker_governance",
            f"Gobernanza semántica ejecutada: {governance.get('status', 'unknown')}.",
            extracted_pattern=str(governance),
        )
        return {"status": "completed", "governance": governance, "qualia": qualia}

    def _neuron_candidate_formation(self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
        pulse = {"status": "unknown", "summary": "worker background scan", "federation": {"android_native_online": 0, "android_llm_hosts": 0}}
        raw = candidates_from_system_debt(pulse_summary=pulse)
        formed = form_candidates(raw)
        qualia = self._publish_qualia_experience(
            run_ref, "neuron_candidate_formation", "worker_formation",
            f"Formación de candidatos: {len(raw)} raw → {len(formed)} formados.",
            extracted_pattern=str([c.get("name", "") for c in formed[:5]]),
        )
        return {"status": "completed", "raw_count": len(raw), "formed_count": len(formed), "candidates": formed, "qualia": qualia}

    def _experimental_neuron_activity(self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
        from triade.core.neuron_mission_selector import select_relevant_missions
        from triade.core.neuron_missions import NeuronMissionStore

        mission_id = task.payload.get("mission_id")
        if mission_id is not None:
            store = NeuronMissionStore(db_path=self.db_path)
            mission = store.get_mission(int(mission_id))
            selection = select_relevant_missions(
                user_input=str(task.payload.get("query") or task.payload.get("user_input") or ""),
                domain=str(task.payload.get("domain") or (mission.domain if mission else "") or ""),
                memory_context=task.payload.get("memory_context") or task.payload.get("context") or {},
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
                    extracted_pattern=str({"mission_id": mission_id, "decision": "mission_not_found"}),
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
                    extracted_pattern=str({
                        "mission_id": mission_id,
                        "decision": "blocked_by_relevance",
                        "selected_count": selection.get("count", 0),
                    }),
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
                str(mission_result.get("observation") or mission_result.get("decision") or "Misión neuronal ejecutada."),
                extracted_pattern=str({
                    "mission_id": mission_result.get("mission_id"),
                    "cycle_id": mission_result.get("cycle_id"),
                    "evidence_id": mission_result.get("evidence_id"),
                    "score_id": mission_result.get("score_id"),
                    "decision": mission_result.get("decision"),
                }),
                proposed_learning=str(mission_result.get("proposed_learning") or "")[:1000],
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

        signals = SignalPacket(run_id=run_ref, intent="worker", tone="operational", urgency="low", risk="low", notes=["background"])
        query = str(task.payload.get("query") or "pulso memoria federacion modelo estado worker")
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
                task_payload={**task.payload, "selected_by_relevance": True, "selection_result": selection},
                task_dir=task_dir,
                config=config,
            )
            qualia = self._publish_qualia_experience(
                run_ref,
                "experimental_neuron_activity",
                "worker_neuron_relevant_mission",
                str(mission_result.get("observation") or mission_result.get("decision") or "Misión neuronal ejecutada por relevancia."),
                extracted_pattern=str({
                    "mission_id": mission_result.get("mission_id"),
                    "cycle_id": mission_result.get("cycle_id"),
                    "evidence_id": mission_result.get("evidence_id"),
                    "score_id": mission_result.get("score_id"),
                    "decision": mission_result.get("decision"),
                    "relevance_count": selection.get("count"),
                }),
                proposed_learning=str(mission_result.get("proposed_learning") or "")[:1000],
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
            edge_usage={"used_edge": False, "accepted": False, "keywords": ["pulso", "memoria", "federacion"]},
            system_events=[],
        )
        ids = NeuronActivityStore(db_path=self.db_path).record_run_activity(run_ref, activity)
        activity["db_activity_ids"] = ids
        qualia = self._publish_qualia_experience(
            run_ref, "experimental_neuron_activity", "worker_neuron_activity",
            f"Actividad experimental: {len(ids)} registros de actividad.",
            extracted_pattern=str(activity.get("summary", "")),
        )
        return {"status": "completed", "activity": activity, "qualia": qualia}

    def _neuron_autopromotion(self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
        events = NeuronAutopromoter(db_path=self.db_path).promote()
        qualia = self._publish_qualia_experience(
            run_ref, "neuron_autopromotion", "worker_autopromotion",
            f"Auto-promoción ejecutada: {len(events)} eventos.",
            extracted_pattern=str(events[:3]),
        )
        return {"status": "completed", "events": events, "stable_promotion_requires_readiness": True, "qualia": qualia}

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
            try:
                pipe.mark_used_in_run(
                    candidate["candidate_id"], run_ref, outcome_score=0.80,
                )
                promoted.append({"candidate_id": candidate.get("candidate_id"), "action": "marked_used_in_run"})
            except ValueError as exc:
                promoted.append({"candidate_id": candidate.get("candidate_id"), "action": "skipped", "reason": str(exc)})
        return {"status": "completed", "run_tracking_updates": promoted, "stable_memory_written": False}

    def _stable_consolidation_review(self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
        """Revisa candidatos con evidencia suficiente y solo entonces permite consolidar."""
        pipe = LearningPipeline(db_path=self.db_path)
        sandbox = WorkerSandbox(task_dir)
        consolidated = []
        rejected = []
        for candidate in pipe.list_candidates(status="validated_in_runs", limit=5):
            sb = sandbox.run("analyze_memory_candidate", candidate, timeout=config.task_timeout)
            if sb.get("status") != "ok" or not candidate.get("source_ref"):
                rejected.append({"candidate_id": candidate.get("candidate_id"), "reason": "sandbox_check_failed"})
                continue
            try:
                result = pipe.consolidate(candidate["candidate_id"], approved_by=f"worker-stable-review:{run_ref}")
                consolidated.append({
                    "candidate_id": candidate.get("candidate_id"),
                    "document_id": result.get("semantic_document_id"),
                    "status": "consolidated",
                })
            except ValueError as exc:
                rejected.append({"candidate_id": candidate.get("candidate_id"), "reason": str(exc)})
        qualia = self._publish_qualia_experience(
            run_ref, "stable_consolidation_review", "worker_stable_review",
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
        qualia = self._publish_qualia_experience(
            run_ref, "system_debt_scan", "worker_debt",
            "Deuda operacional detectada: ciclo observar→evaluar→sandbox→memoria experimental→medición.",
            proposed_learning="Mantener vivo el ciclo de observación y evaluación continua.",
        )
        return {"status": "completed", "learning_candidate": candidate, "qualia": qualia}

    def _bodega_global_review(self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
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
            extracted_pattern=str({
                "memory_confidence": mem_conf,
                "episodes_count": episodes_count,
                "candidates_count": candidates_count,
                "verified_count": verified_count,
                "stable_needs_review": needs_review,
                "contradictions_count": len(contradictions),
            })[:1000],
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

    def _shell_execute(self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig) -> dict[str, Any]:
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
            except Exception:
                pass

        return result

    def _artifact_dir(self, run_ref: str) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return self.runs_dir / f"{stamp}-{run_ref[-8:]}"

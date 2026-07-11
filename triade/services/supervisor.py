"""Supervisor local de runtime 24/7 para Tríade Ω."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4

from triade.core.contracts import utc_now
from triade.core.error_bus import query_internal_errors, record_internal_error
from triade.core.life_pulse import LIFE_PULSE
from triade.core.neuron_missions import NeuronMissionStore
from triade.core.neuron_nutrition import run_neuron_nutrition_cycle
from triade.core.qualia import QUALIA
from triade.learning.pipeline import LearningPipeline
from triade.core.bodega import Bodega
from triade.models.hardware_profile import HardwareProfiler
from triade.models.model_router import ModelRouter
from triade.models.ollama_client import OllamaClient
from triade.qualia.bus import QualiaBus
from triade.workers.background_service import WorkerBackgroundService
from triade.workers.mission_planner import MissionPlanner
from triade.workers.neuron_mission_executor import NeuronMissionExecutor
from triade.workers.state_store import WorkerStateStore

from .event_bus import build_context_from_events, list_recent_events, publish_event


AUTONOMY_LEVELS = ("observe_only", "learn_candidates", "execute_missions", "full_local")
AUTONOMY_RANK = {name: index for index, name in enumerate(AUTONOMY_LEVELS)}


class InternalRuntimeSupervisor:
    """Orquesta observación, misiones, aprendizaje y observabilidad local."""

    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        runs_dir: str | Path = "runs/background",
        *,
        mode: str | None = None,
        enabled: bool | None = None,
        interval_seconds: int | None = None,
        max_cycles: int | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.mode = self._normalize_mode(mode or os.environ.get("TRIADE_RUNTIME_MODE", "observe_only"))
        self.enabled = enabled if enabled is not None else self._env_flag("TRIADE_RUNTIME_ENABLED", default=False)
        self.interval_seconds = max(1, int(interval_seconds or os.environ.get("TRIADE_RUNTIME_INTERVAL_SECONDS", "30") or 30))
        self.max_cycles = max(0, int(max_cycles or os.environ.get("TRIADE_RUNTIME_MAX_CYCLES", "0") or 0))
        self.runtime_id = f"runtime-{uuid4().hex[:12]}"
        self.started_at = utc_now()
        self.lock_file = self.runs_dir / ".triade_runtime.lock"
        self.stop_file = self.runs_dir / ".triade_runtime.stop"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.counters: Counter[str] = Counter()
        self.last_events: list[dict[str, Any]] = []
        self.last_context_snapshot: dict[str, Any] = {}
        self.safety_policy = {
            "identity_core_modified": False,
            "stable_memory_written": False,
            "external_network_by_default": False,
            "shell_by_default": False,
            "default_mode": "observe_only",
            "requires_explicit_activation": True,
        }
        self.self_test_cycle_count = 0
        self.self_test_every_cycles = int(os.environ.get("TRIADE_SELF_TEST_EVERY_CYCLES", "5") or "5")
        self.last_self_test_result: dict[str, Any] | None = None

    @staticmethod
    def _env_flag(name: str, default: bool = False) -> bool:
        value = str(os.environ.get(name, "1" if default else "0") or "0").strip().lower()
        return value in {"1", "true", "yes", "on"}

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        clean = str(mode or "observe_only").strip().lower()
        return clean if clean in AUTONOMY_RANK else "observe_only"

    def configure(
        self,
        *,
        mode: str | None = None,
        enabled: bool | None = None,
        interval_seconds: int | None = None,
        max_cycles: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if mode is not None:
                self.mode = self._normalize_mode(mode)
            if enabled is not None:
                self.enabled = bool(enabled)
            if interval_seconds is not None:
                self.interval_seconds = max(1, int(interval_seconds))
            if max_cycles is not None:
                self.max_cycles = max(0, int(max_cycles))
        return self.snapshot()

    def run_once(self, mode: str | None = None) -> dict[str, Any]:
        current_mode = self._normalize_mode(mode or self.mode)
        with self._lock:
            self.last_context_snapshot = {}
        cycle_id = f"cycle-{uuid4().hex[:10]}"
        publish_event(
            "runtime_cycle_start",
            "internal_runtime",
            {"runtime_id": self.runtime_id, "cycle_id": cycle_id, "mode": current_mode},
            db_path=self.db_path,
            run_ref=self.runtime_id,
        )
        snapshot = self._build_snapshot()
        self.last_context_snapshot = snapshot

        results: dict[str, Any] = {
            "status": "ok",
            "runtime_id": self.runtime_id,
            "cycle_id": cycle_id,
            "mode": current_mode,
            "enabled": self.enabled,
            "services": {},
            "counters": dict(self.counters),
        }

        # ── Resource Governor ──────────────────────────────────────────
        governor = self._run_governor(current_mode)
        effective_mode = governor.get("effective_mode", current_mode)
        perm = governor.get("permissions", {})
        results["governor"] = governor

        try:
            if effective_mode in ("cooldown", "blocked"):
                publish_event(
                    "runtime_cycle_skipped_resource_cooldown",
                    "internal_runtime",
                    {
                        "cycle_id": cycle_id,
                        "mode": current_mode,
                        "effective_mode": effective_mode,
                        "reason": governor.get("reason", ""),
                    },
                    severity="warning",
                    db_path=self.db_path,
                    run_ref=self.runtime_id,
                )
                results["status"] = "skipped"
                results["skipped_reason"] = governor.get("reason", "Cooldown por recursos.")
                self.counters["cycles"] += 1
                self.last_events = list_recent_events(limit=20, db_path=self.db_path)
                publish_event(
                    "runtime_cycle_complete",
                    "internal_runtime",
                    {"cycle_id": cycle_id, "mode": current_mode, "skipped": True, "effective_mode": effective_mode},
                    db_path=self.db_path,
                    run_ref=self.runtime_id,
                )
                results["counters"] = dict(self.counters)
                results["snapshot"] = self.snapshot()
                return results

            results["services"]["memory_service"] = self._memory_service(current_mode)
            results["services"]["qualia_service"] = self._qualia_service(current_mode)
            results["services"]["model_service"] = self._model_service(current_mode)
            results["services"]["observability_service"] = self._observability_service(current_mode)
            if AUTONOMY_RANK[current_mode] >= AUTONOMY_RANK["learn_candidates"]:
                results["services"]["mission_service"] = self._governed_mission_service(current_mode, governor)
            if AUTONOMY_RANK[current_mode] >= AUTONOMY_RANK["full_local"]:
                results["services"]["learning_service"] = self._governed_learning_service(current_mode, governor)
            self.self_test_cycle_count += 1
            if self.self_test_cycle_count % self.self_test_every_cycles == 0:
                try:
                    from triade.core.self_test_cycle import run_self_test_cycle
                    self.last_self_test_result = run_self_test_cycle(
                        mode="safe", db_path=self.db_path, runs_dir=self.runs_dir,
                    )
                    results["self_test"] = self.last_self_test_result
                except Exception as st_exc:
                    self.last_self_test_result = {"status": "error", "error": str(st_exc)}
                    results["self_test"] = self.last_self_test_result
            self.counters["cycles"] += 1
            self.last_events = list_recent_events(limit=20, db_path=self.db_path)
            publish_event(
                "runtime_cycle_complete",
                "internal_runtime",
                {"runtime_id": self.runtime_id, "cycle_id": cycle_id, "mode": current_mode, "services": list(results["services"].keys())},
                db_path=self.db_path,
                run_ref=self.runtime_id,
            )
            results["counters"] = dict(self.counters)
            results["snapshot"] = self.snapshot()
            return results
        except Exception as exc:
            self.counters["errors"] += 1
            record_internal_error(
                "internal_runtime.run_once",
                exc,
                run_id=self.runtime_id,
                payload={"cycle_id": cycle_id, "mode": current_mode},
                db_path=self.db_path,
            )
            publish_event(
                "runtime_cycle_error",
                "internal_runtime",
                {"runtime_id": self.runtime_id, "cycle_id": cycle_id, "mode": current_mode, "error": str(exc)},
                severity="error",
                db_path=self.db_path,
                run_ref=self.runtime_id,
            )
            return {
                "status": "error",
                "runtime_id": self.runtime_id,
                "cycle_id": cycle_id,
                "mode": current_mode,
                "error": str(exc),
                "snapshot": self.snapshot(),
            }

    def _run_governor(self, mode: str) -> dict[str, Any]:
        """Ejecuta Resource Governor + Permission Governor."""
        from triade.core.resource_probe import build_resource_probe
        from triade.core.resource_governor import decide_work_mode
        from triade.core.permission_governor import build_permission_profile
        from triade.core.ollama_blood import check_ollama_blood

        probe = build_resource_probe()
        blood = check_ollama_blood()
        decision = decide_work_mode(probe, blood, mode)
        permissions = build_permission_profile(decision.get("effective_mode", mode))

        publish_event(
            "work_mode_decided",
            "resource_governor",
            {
                "requested": mode,
                "allowed": decision.get("allowed_mode"),
                "effective": decision.get("effective_mode"),
                "reason": decision.get("reason", ""),
            },
            db_path=self.db_path,
            run_ref=self.runtime_id,
        )

        return {**decision, "permissions": permissions, "resource_probe": probe}

    def _governed_mission_service(self, mode: str, governor: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta misiones con degradación local segura y explícita."""
        if not governor.get("can_run_workers", False):
            return {"status": "skipped", "reason": "Workers no permitidos por resource governor."}
        return self._mission_service(mode)

    def _governed_learning_service(self, mode: str, governor: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta aprendizaje solo si permisos lo permiten."""
        if not governor.get("can_evaluate_learning", False):
            return {"status": "skipped", "reason": "Evaluación no permitida por resource governor."}
        return self._learning_service(mode)

    def run_forever(self, interval_seconds: int = 30, max_cycles: int = 0, mode: str | None = None) -> dict[str, Any]:
        self.configure(mode=mode, enabled=True, interval_seconds=interval_seconds, max_cycles=max_cycles)
        self._stop.clear()
        self.lock_file.write_text(self.runtime_id, encoding="utf-8")
        try:
            cycle = 0
            while not self._stop.is_set():
                if self.stop_file.exists():
                    break
                self.run_once(mode=self.mode)
                cycle += 1
                if self.max_cycles > 0 and cycle >= self.max_cycles:
                    break
                self._stop.wait(max(1, self.interval_seconds))
            return self.snapshot()
        finally:
            self.enabled = False
            try:
                self.lock_file.unlink()
            except FileNotFoundError:
                pass
            try:
                self.stop_file.unlink()
            except FileNotFoundError:
                pass

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        self.stop_file.write_text(utc_now(), encoding="utf-8")
        publish_event(
            "runtime_stop_requested",
            "internal_runtime",
            {"runtime_id": self.runtime_id},
            db_path=self.db_path,
            run_ref=self.runtime_id,
        )
        return {"status": "stop_requested", "runtime_id": self.runtime_id, "stop_file": str(self.stop_file)}

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "runtime_id": self.runtime_id,
            "started_at": self.started_at,
            "mode": self.mode,
            "enabled": self.enabled,
            "running": bool(self._thread and self._thread.is_alive()),
            "services": self._build_services_snapshot(),
            "counters": dict(self.counters),
            "last_events": self.last_events[-20:],
            "last_context_snapshot": self.last_context_snapshot,
            "safety_policy": self.safety_policy,
            "files": {
                "lock_file": str(self.lock_file),
                "stop_file": str(self.stop_file),
            },
        }

    def _build_snapshot(self) -> dict[str, Any]:
        return {
            "runtime": {
                "runtime_id": self.runtime_id,
                "started_at": self.started_at,
                "mode": self.mode,
                "enabled": self.enabled,
            },
            "services": self._build_services_snapshot(),
            "counters": dict(self.counters),
            "events": build_context_from_events(limit=20, db_path=self.db_path),
        }

    def _build_services_snapshot(self) -> dict[str, Any]:
        worker_service = WorkerBackgroundService(db_path=self.db_path, runs_dir=self.runs_dir)
        learning = LearningPipeline(db_path=self.db_path)
        mission_store = NeuronMissionStore(db_path=self.db_path)
        missions = mission_store.list_missions(limit=20)
        active_missions = [m for m in missions if m.status in {"experimental", "stable"}]
        try:
            ollama_health = OllamaClient().health()
        except Exception as exc:
            ollama_health = {"ok": False, "error": str(exc)}
        hardware = HardwareProfiler().detect()
        router = ModelRouter(available_models=ollama_health.get("models", []) if isinstance(ollama_health, dict) else [], hardware=hardware)
        model_route = router.route_many(intent="runtime", urgency="medium")
        model_decisions = model_route.get("decisions", {}) if isinstance(model_route, dict) else {}
        return {
            "life_pulse": LIFE_PULSE.snapshot(),
            "worker_loop": worker_service.status(),
            "mission_planner": {
                "active_missions": len(active_missions),
                "missions": [m.to_dict() for m in active_missions[:5]],
                "next_plan_preview": [item.to_dict() for item in MissionPlanner(db_path=self.db_path).plan_cycle(run_ref=self.runtime_id)[:5]],
            },
            "neuron_mission_executor": {
                "available": True,
                "safe_local_only": True,
            },
            "qualia_bus": QUALIA.snapshot(refresh_life=False),
            "learning_pipeline": learning.doctor(),
            "semantic_memory": Bodega(db_path=self.db_path).doctor(runs_dir=self.runs_dir),
            "federation": {
                "status": "ok",
                "doctor": None,
            },
            "nutrition": {
                "available": True,
                "mode_hint": self.mode,
            },
            "model_router": {
                "hardware": hardware.to_dict(),
                "ollama": ollama_health,
                "recommendations": model_decisions,
            },
            "errors": {
                "count": len(query_internal_errors(limit=10, db_path=self.db_path)),
                "recent": query_internal_errors(limit=5, db_path=self.db_path),
            },
        }

    def _memory_service(self, mode: str) -> dict[str, Any]:
        bodega = Bodega(db_path=self.db_path)
        doctor = bodega.doctor(runs_dir=self.runs_dir)
        episodes = bodega.list_recent_episodes(limit=10)
        gaps = max(0, int(doctor.get("runs", 0) or 0) - int(doctor.get("episodes", 0) or 0))
        created_candidate = None
        if AUTONOMY_RANK[mode] >= AUTONOMY_RANK["learn_candidates"] and gaps > 0:
            pipe = LearningPipeline(db_path=self.db_path)
            source_ref = f"runtime:{self.runtime_id}:memory-gap"
            existing = [item for item in pipe.list_candidates(status="candidate", limit=100) if item.get("source_ref") == source_ref]
            if not existing:
                created_candidate = pipe.ingest(
                    content=f"Gap operativo detectado por runtime: runs={doctor.get('runs', 0)} episodes={doctor.get('episodes', 0)}.",
                    source_type="tool",
                    source_ref=source_ref,
                    title="Runtime memory gap scan",
                    domain="runtime",
                    risk_level="low",
                )
                self.counters["learning_candidates_created"] += 1
                publish_event(
                    "learning_candidate_created",
                    "memory_service",
                    {"candidate_id": created_candidate.get("candidate_id"), "source_ref": source_ref, "reason": "memory_gap"},
                    db_path=self.db_path,
                    run_ref=self.runtime_id,
                )
        return {
            "status": "ok",
            "gap_count": gaps,
            "recent_episodes": episodes,
            "created_candidate": created_candidate,
            "mode": mode,
        }

    def _mission_service(self, mode: str) -> dict[str, Any]:
        planner = MissionPlanner(db_path=self.db_path)
        planned = planner.plan_cycle(run_ref=self.runtime_id)
        planned_dicts = [item.to_dict() for item in planned]
        self.counters["tasks_planned"] += len(planned_dicts)
        nutrition = None
        if AUTONOMY_RANK[mode] >= AUTONOMY_RANK["learn_candidates"]:
            nutrition = run_neuron_nutrition_cycle(
                db_path=self.db_path,
                runs_dir=self.runs_dir,
                mode=mode,
                limit=5,
            )
            self.counters["tasks_executed"] += int(nutrition.get("missions_executed") or 0)
            self.counters["missions_executed"] += int(nutrition.get("missions_executed") or 0)
            self.counters["learning_candidates_created"] += int(nutrition.get("candidates_created") or 0)
            publish_event(
                "missions_executed",
                "mission_service",
                {"planned_count": len(planned_dicts), "nutrition_result": nutrition},
                db_path=self.db_path,
                run_ref=self.runtime_id,
            )
        publish_event(
            "missions_planned",
            "mission_service",
            {"planned_count": len(planned_dicts), "planned": planned_dicts[:5]},
            db_path=self.db_path,
            run_ref=self.runtime_id,
        )
        return {"status": "ok", "planned": planned_dicts, "nutrition": nutrition}

    def _learning_service(self, mode: str) -> dict[str, Any]:
        pipe = LearningPipeline(db_path=self.db_path, enforce_model_policy=True)
        processed = []
        for candidate in pipe.list_candidates(status="candidate", limit=10):
            try:
                processed.append(pipe.evaluate(candidate["candidate_id"]))
                self.counters["learning_candidates_evaluated"] += 1
                publish_event(
                    "learning_candidate_evaluated",
                    "learning_service",
                    {"candidate_id": candidate.get("candidate_id"), "status": "evaluated"},
                    db_path=self.db_path,
                    run_ref=self.runtime_id,
                )
            except Exception as exc:
                record_internal_error("internal_runtime.learning.evaluate", exc, run_id=self.runtime_id, db_path=self.db_path)
        for candidate in pipe.list_candidates(status="evaluated", limit=10):
            try:
                processed.append(pipe.verify(candidate["candidate_id"]))
                self.counters["learning_candidates_evaluated"] += 1
                publish_event(
                    "learning_candidate_verified",
                    "learning_service",
                    {"candidate_id": candidate.get("candidate_id"), "status": "verified"},
                    db_path=self.db_path,
                    run_ref=self.runtime_id,
                )
            except Exception as exc:
                record_internal_error("internal_runtime.learning.verify", exc, run_id=self.runtime_id, db_path=self.db_path)
        return {"status": "ok", "processed": processed, "mode": mode}

    def _qualia_service(self, mode: str) -> dict[str, Any]:
        qualia = QUALIA.snapshot(refresh_life=False)
        mood = {
            "state": "neutral",
            "valence": 0.0,
            "arousal": 0.0,
            "reason": "operational_state_only_no_human_emotion",
            "mode": mode,
        }
        publish_event(
            "qualia_compacted",
            "qualia_service",
            {"qualia_status": qualia.get("status"), "mood": mood},
            db_path=self.db_path,
            run_ref=self.runtime_id,
        )
        return {"status": "ok", "qualia": qualia, "operational_mood": mood}

    def _model_service(self, mode: str) -> dict[str, Any]:
        try:
            health = OllamaClient().health()
        except Exception as exc:
            health = {"ok": False, "error": str(exc)}
        hardware = HardwareProfiler().detect()
        router = ModelRouter(available_models=health.get("models", []) if isinstance(health, dict) else [], hardware=hardware)
        recommendations = router.route_many(intent="runtime", urgency="medium")
        decisions = recommendations.get("decisions", {}) if isinstance(recommendations, dict) else {}
        if isinstance(decisions, dict) and decisions.get("central"):
            primary = decisions.get("central") or {}
        elif isinstance(decisions, dict):
            primary = next(iter(decisions.values()), {})
        else:
            primary = {}
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """INSERT INTO model_events (run_id, role, provider, model_name, ok, error, quality_score, latency_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.runtime_id,
                    "runtime",
                    "ollama",
                    str(primary.get("selected_model") or "unknown"),
                    1 if bool(health.get("ok")) else 0,
                    None if health.get("ok") else str(health.get("error") or "health_failed"),
                    0.75 if health.get("ok") else 0.0,
                    None,
                    utc_now(),
                ),
            )
        publish_event(
            "model_service_checked",
            "model_service",
            {"health_ok": bool(health.get("ok")), "recommendations": [item.to_dict() for item in recommendations] if isinstance(recommendations, list) else []},
            db_path=self.db_path,
            run_ref=self.runtime_id,
        )
        return {
            "status": "ok",
            "mode": mode,
            "hardware": hardware.to_dict(),
            "ollama": health,
            "recommendations": decisions,
        }

    def _observability_service(self, mode: str) -> dict[str, Any]:
        worker = WorkerStateStore(db_path=self.db_path).doctor()
        missions = NeuronMissionStore(db_path=self.db_path)
        learning = LearningPipeline(db_path=self.db_path).doctor()
        recent_errors = query_internal_errors(limit=10, db_path=self.db_path)
        recent_events = list_recent_events(limit=10, db_path=self.db_path)
        payload = {
            "status": "ok",
            "mode": mode,
            "worker": worker,
            "missions": {
                "total": len(missions.list_missions(limit=100)),
                "active": len([m for m in missions.list_missions(limit=100) if m.status in {"experimental", "stable"}]),
            },
            "learning": learning,
            "errors": recent_errors,
            "events": recent_events,
        }
        publish_event("observability_snapshot", "observability_service", payload, db_path=self.db_path, run_ref=self.runtime_id)
        return payload

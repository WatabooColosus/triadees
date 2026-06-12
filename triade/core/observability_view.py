"""Vista unificada de observabilidad operacional de Tríade Ω."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .bodega import Bodega
from .error_bus import query_internal_errors, record_internal_error
from .neuron_identity_view import NeuronIdentityView
from .repo_info import repo_info
from triade.federation.federation import Federation
from triade.learning.pipeline import LearningPipeline
from triade.memory.semantic_store import SemanticMemoryStore
from triade.models.ollama_client import OllamaClient
from triade.qualia.store import QualiaStore
from triade.workers.background_service import WorkerBackgroundService


@dataclass(slots=True)
class TriadeObservabilityView:
    """Compone fuentes existentes en una respuesta estable para UI/API."""

    db_path: str | Path = "triade/memory/triade.db"
    runs_dir: str | Path = "runs"
    worker_runs_dir: str | Path = "runs/background"
    system_pulse_fn: Callable[..., dict[str, Any]] | None = None
    health_fn: Callable[[], dict[str, Any]] | None = None

    def build(self, limit: int = 20) -> dict[str, Any]:
        warnings: list[str] = []
        degraded_sources: list[str] = []

        def collect(name: str, fn: Callable[[], Any], fallback: Any) -> Any:
            try:
                return fn()
            except Exception as exc:
                degraded_sources.append(name)
                warnings.append(f"{name} no disponible; se devuelve estado degradado.")
                record_internal_error(
                    f"observability.{name}",
                    exc,
                    payload={"view": "TriadeObservabilityView"},
                    db_path=self.db_path,
                )
                return fallback

        bodega = collect("bodega", lambda: Bodega(db_path=self.db_path).doctor(runs_dir=self.runs_dir), self._empty_bodega())
        pulse = collect(
            "system_pulse",
            lambda: self.system_pulse_fn(sync_relay=False) if self.system_pulse_fn else {},
            {},
        )
        health = collect("health", self.health_fn, {}) if self.health_fn else {}
        workers = collect("workers", lambda: self._workers(limit), self._empty_workers())
        learning = collect("learning", lambda: self._learning(limit), self._empty_learning())
        neurons = collect("neurons", lambda: NeuronIdentityView(self.db_path, self.runs_dir).list(limit=limit), self._empty_neurons())
        qualia = collect("qualia", lambda: self._qualia(limit), self._empty_qualia())
        federation = collect("federation", lambda: self._federation(limit), self._empty_federation())
        semantic = collect("semantic_memory", lambda: SemanticMemoryStore(db_path=self.db_path).doctor(), {})
        models = collect("models", self._models, {"status": "unknown", "ollama": {"ok": False}})
        recent_errors = collect("internal_errors", lambda: query_internal_errors(limit=limit, db_path=self.db_path), [])
        last_run = collect("last_run", self._last_run, None)
        memory_trace = collect("memory_trace", lambda: self._last_run_memory_trace(), {})

        status = "ok"
        if recent_errors:
            status = "degraded"
        if degraded_sources:
            status = "degraded"

        return {
            "status": status,
            "mode": "triade_observability_view",
            "timestamp": self._now(),
            "repo": repo_info(),
            "last_run": last_run or {"message": "No hay runs registrados todavía."},
            "memory_trace": memory_trace,
            "bodega": bodega,
            "workers": workers,
            "learning": learning,
            "neurons": neurons,
            "qualia": qualia,
            "federation": federation,
            "semantic_memory": semantic,
            "models": models,
            "health": health,
            "system_pulse": pulse,
            "internal_errors": {
                "count": len(recent_errors),
                "errors": recent_errors,
                "message": None if recent_errors else "No hay errores internos recientes.",
            },
            "warnings": warnings,
            "degraded_sources": degraded_sources,
            "empty_messages": {
                "runs": "No hay runs registrados todavía.",
                "errors": "No hay errores internos recientes.",
                "workers": "No hay workers activos.",
                "learning": "No hay candidatos de aprendizaje pendientes.",
            },
        }

    def _workers(self, limit: int) -> dict[str, Any]:
        service = WorkerBackgroundService(db_path=self.db_path, runs_dir=self.worker_runs_dir)
        status = service.status()
        events = service.events(limit=limit)
        queue = service.queue_status(limit=limit)
        last_error = next((e for e in events.get("events", []) if e.get("status") == "error"), None)
        return {
            "status": "ok",
            "active": bool(status.get("running")),
            "running": bool(status.get("running")),
            "last_cycle": status.get("last_run"),
            "pending_tasks": int((status.get("task_counts") or {}).get("pending", 0)),
            "task_counts": status.get("task_counts") or {},
            "run_counts": status.get("run_counts") or {},
            "last_events": events.get("events", []),
            "last_error": last_error,
            "queue": queue,
            "message": None if status.get("running") else "No hay workers activos.",
        }

    def _learning(self, limit: int) -> dict[str, Any]:
        pipe = LearningPipeline(db_path=self.db_path)
        doctor = pipe.doctor()
        pending: list[dict[str, Any]] = []
        for state in ("candidate", "evaluated", "verified", "validated_in_runs"):
            pending.extend(pipe.list_candidates(status=state, limit=limit))
        counts = doctor.get("candidates_by_status") or {}
        return {
            "status": "ok",
            "candidates_by_status": counts,
            "pending": pending[:limit],
            "pending_count": len(pending[:limit]),
            "consolidated": int(counts.get("consolidated", 0) or 0),
            "rejected": int(counts.get("rejected", 0) or 0),
            "policy": doctor.get("policy"),
            "message": None if pending else "No hay candidatos de aprendizaje pendientes.",
        }

    def _qualia(self, limit: int) -> dict[str, Any]:
        store = QualiaStore(db_path=self.db_path)
        return {
            "status": "ok",
            "doctor": store.doctor(),
            "latest_state": store.latest_state(),
            "recent_states": store.list_states(limit=limit),
            "recent_signals": store.list_signals(limit=limit),
            "recent_experiences": store.list_experiences(limit=limit),
        }

    def _federation(self, limit: int) -> dict[str, Any]:
        doctor = Federation(db_path=self.db_path).doctor()
        with self._connect() as conn:
            nodes = [dict(r) for r in conn.execute(
                "SELECT node_id, name, trust_level, status, last_seen_at, capability_status FROM federated_nodes ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()]
            exchanges = [dict(r) for r in conn.execute(
                "SELECT exchange_id, source_node_id, target_node_id, exchange_type, decision, safety_status, created_at FROM federated_exchange_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()]
        active = [n for n in nodes if n.get("status") == "active"]
        revoked = [n for n in nodes if n.get("status") == "revoked"]
        return {
            "status": "ok",
            "doctor": doctor,
            "active_nodes": active,
            "revoked_nodes": revoked,
            "active_count": len(active),
            "revoked_count": len(revoked),
            "recent_exchanges": exchanges,
        }

    def _models(self) -> dict[str, Any]:
        ollama = OllamaClient().health()
        return {
            "status": "ok" if ollama.get("ok") else "degraded",
            "ollama": ollama,
            "local_required": False,
            "policy": "Ollama es opcional; el sistema puede correr sin red externa ni modelo local.",
        }

    def _last_run(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT run_id, source, user_input, status, created_at, model_hypothalamus, model_central FROM runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def _last_run_memory_trace(self) -> dict[str, Any]:
        """Lee memory_trace del último run desde sus artifacts."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT run_id FROM runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return {}
        run_id = row["run_id"]
        run_dir = Path(self.runs_dir) / run_id
        memory_diff_path = run_dir / "memory_diff.json"
        if not memory_diff_path.exists():
            return {}
        try:
            data = json.loads(memory_diff_path.read_text(encoding="utf-8"))
            trace = data.get("memory_trace")
            if not trace:
                return {}
            from .schemas import MemoryTraceResponse
            response = MemoryTraceResponse(
                run_id=trace.get("run_id", run_id),
                memory_confidence=trace.get("memory_confidence", "low"),
                memory_confidence_score=float(trace.get("memory_confidence_score", 0.0)),
                identity_matches_count=int(trace.get("identity_matches_count", 0)),
                semantic_matches_count=int(trace.get("semantic_matches_count", 0)),
                episodic_matches_count=int(trace.get("episodic_matches_count", 0)),
                authorized_matches_count=len(trace.get("authorized_matches", [])),
                quarantined_matches_count=len(trace.get("quarantined_matches", [])),
                contradictions_count=len(trace.get("contradictions", [])),
                stable_needs_review=int((trace.get("stable_audit_summary") or {}).get("stable_needs_review", 0)),
                created_at=trace.get("created_at"),
            )
            return response.model_dump()
        except Exception:
            return {}

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _now() -> str:
        from .contracts import utc_now
        return utc_now()

    @staticmethod
    def _empty_bodega() -> dict[str, Any]:
        return {"status": "empty", "counts": {"runs": 0, "episodes": 0}}

    @staticmethod
    def _empty_workers() -> dict[str, Any]:
        return {"status": "ok", "active": False, "pending_tasks": 0, "last_events": [], "last_error": None, "message": "No hay workers activos."}

    @staticmethod
    def _empty_learning() -> dict[str, Any]:
        return {"status": "ok", "candidates_by_status": {}, "pending": [], "consolidated": 0, "rejected": 0, "message": "No hay candidatos de aprendizaje pendientes."}

    @staticmethod
    def _empty_neurons() -> dict[str, Any]:
        return {"status": "ok", "mode": "neuron_identity_view", "summary": {"total_neurons": 0, "by_status": {}}, "neurons": []}

    @staticmethod
    def _empty_qualia() -> dict[str, Any]:
        return {"status": "ok", "latest_state": None, "recent_states": [], "recent_signals": [], "recent_experiences": []}

    @staticmethod
    def _empty_federation() -> dict[str, Any]:
        return {"status": "ok", "active_nodes": [], "revoked_nodes": [], "active_count": 0, "revoked_count": 0, "recent_exchanges": []}

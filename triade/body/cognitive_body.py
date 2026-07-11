"""Vista auditable del cuerpo computacional local de Tríade Ω.

Este módulo resume señales operativas ya existentes. No atribuye conciencia,
voluntad ni autonomía fuera de las capacidades verificables del runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now


def get_internal_runtime_state(**kwargs: Any) -> dict[str, Any]:
    """Adaptador perezoso para evitar ciclos de importación al cargar el módulo."""

    from triade.core.internal_runtime import get_internal_runtime_state as implementation

    return implementation(**kwargs)


def build_runtime_heartbeat(**kwargs: Any) -> dict[str, Any]:
    """Adaptador perezoso del pulso interno."""

    from triade.core.internal_runtime import build_runtime_heartbeat as implementation

    return implementation(**kwargs)


def build_learning_journal(**kwargs: Any) -> dict[str, Any]:
    """Adaptador perezoso del diario de aprendizaje."""

    from triade.core.learning_journal import build_learning_journal as implementation

    return implementation(**kwargs)


class WorkerBackgroundService:
    """Proxy perezoso para el servicio real de workers."""

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        from triade.workers.background_service import WorkerBackgroundService as implementation

        return implementation(*args, **kwargs)


@dataclass(slots=True)
class CognitiveBody:
    """Construye una instantánea de estado sin mutar el runtime."""

    db_path: str | Path = "triade/memory/triade.db"
    runs_dir: str | Path = "runs/background"

    def snapshot(self, *, since_hours: int = 24, limit: int = 50) -> dict[str, Any]:
        runtime = get_internal_runtime_state(db_path=self.db_path, runs_dir=self.runs_dir)
        heartbeat = build_runtime_heartbeat(
            db_path=self.db_path,
            runs_dir=self.runs_dir,
            since_hours=since_hours,
            limit=limit,
        )
        workers = WorkerBackgroundService(db_path=self.db_path, runs_dir=self.runs_dir).status()
        learning = build_learning_journal(
            db_path=self.db_path,
            since_hours=since_hours,
            limit=limit,
        )

        recent_events = heartbeat.get("recent_events") or heartbeat.get("last_events") or []
        nervous_system = {
            "sensory_periphery": {
                "source": "events_and_project_context",
                "status": "active" if recent_events else "quiet",
                "signals": len(recent_events),
            },
            "central_integration": {
                "runtime_enabled": bool(runtime.get("enabled")),
                "mode": runtime.get("mode"),
                "services": runtime.get("services", {}),
            },
            "hippocampus": {
                "learning_candidates": int(learning.get("candidates_created", 0) or 0),
                "consolidations": int(learning.get("consolidations", 0) or 0),
                "journal_status": learning.get("status", "unknown"),
            },
            "cerebellum": {
                "workers_running": bool(workers.get("running")),
                "queued_tasks": int(workers.get("queued", 0) or 0),
                "worker_status": workers.get("status", "unknown"),
            },
            "homeostasis": {
                "runtime_state": heartbeat.get("runtime_activity_state", "unknown"),
                "degraded_components": heartbeat.get("degraded_components", []),
                "blocked_learning_actions": heartbeat.get("blocked_learning_actions", []),
                "ollama_blood": heartbeat.get("ollama_blood", {}),
            },
        }

        alive = bool(
            nervous_system["central_integration"]["runtime_enabled"]
            or nervous_system["cerebellum"]["workers_running"]
            or heartbeat.get("cycles_last_24h", 0)
        )

        return {
            "status": "operational" if alive else "dormant",
            "entity": "Tríade Ω",
            "generated_at": utc_now(),
            "body_version": "0.1.1",
            "nervous_system": nervous_system,
            "heartbeat": heartbeat,
            "learning": learning,
            "workers": workers,
            "claims": {
                "subjective_consciousness": False,
                "persistent_runtime": alive,
                "learning_requires_evidence": True,
                "identity_core_mutable": False,
            },
        }


def build_cognitive_body(
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
    since_hours: int = 24,
    limit: int = 50,
) -> dict[str, Any]:
    """Atajo funcional para consumidores de API y pruebas."""

    return CognitiveBody(db_path=db_path, runs_dir=runs_dir).snapshot(
        since_hours=since_hours,
        limit=limit,
    )

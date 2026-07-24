"""TriadeOS — Sistema Operativo Cognitivo para Tríade Ω.

Orquesta de forma permanente:
- Knowledge Graph vivo (nodos, relaciones, contradicciones)
- Motor de eventos activo (trigger → trabajo automático)
- Scheduler prioritario de neuronas
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now
from triade.os.contracts import TriadeOSConfig
from triade.os.event_engine import EventEngine
from triade.os.knowledge_graph import KnowledgeGraph
from triade.os.neuron_scheduler import NeuronScheduler


class TriadeOS:
    """Orquestador principal del Sistema Operativo Cognitivo."""

    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        config: TriadeOSConfig | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.config = config or TriadeOSConfig()
        self._knowledge_graph: KnowledgeGraph | None = None
        self._event_engine: EventEngine | None = None
        self._neuron_scheduler: NeuronScheduler | None = None

    # ── Lazy subsystem init ──────────────────────────────────

    @property
    def knowledge_graph(self) -> KnowledgeGraph:
        if self._knowledge_graph is None:
            self._knowledge_graph = KnowledgeGraph(self.db_path)
        return self._knowledge_graph

    @property
    def event_engine(self) -> EventEngine:
        if self._event_engine is None:
            self._event_engine = EventEngine(self.db_path)
        return self._event_engine

    @property
    def neuron_scheduler(self) -> NeuronScheduler:
        if self._neuron_scheduler is None:
            self._neuron_scheduler = NeuronScheduler(self.db_path)
        return self._neuron_scheduler

    # ── Main cycle ───────────────────────────────────────────

    def cycle(self) -> dict[str, Any]:
        """Ejecuta un ciclo completo de TriadeOS."""
        if not self.config.enabled:
            return {"status": "disabled", "actions": []}

        now = utc_now()
        result: dict[str, Any] = {
            "status": "ok",
            "timestamp": now,
            "actions": [],
        }

        if self.config.event_engine_enabled:
            tasks = self.event_engine.scan()
            result["actions"].append({
                "type": "event_engine_scan",
                "tasks_created": len(tasks),
            })

        if self.config.scheduler_enabled:
            wakeups = self.neuron_scheduler.schedule_wakeups(
                max_wakeups=self.config.max_wakeups_per_cycle,
            )
            result["actions"].append({
                "type": "neuron_schedule",
                "wakeup_count": len(wakeups),
                "wakeup_details": wakeups,
            })

        if self.config.knowledge_graph_enabled:
            self.knowledge_graph.propagate_confidence()
            contradictions = self.knowledge_graph.detect_contradictions()
            result["actions"].append({
                "type": "knowledge_graph_maintenance",
                "contradictions_found": len(contradictions),
            })

        result["summary"] = self._build_summary(result["actions"])
        return result

    # ── Status ───────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        return {
            "triadeos": "active" if self.config.enabled else "disabled",
            "config": self.config.to_dict(),
            "subsystems": {
                "knowledge_graph": self.config.knowledge_graph_enabled,
                "event_engine": self.config.event_engine_enabled,
                "scheduler": self.config.scheduler_enabled,
            },
        }

    def doctor(self) -> dict[str, Any]:
        report: dict[str, Any] = {"status": "ok", "config": self.config.to_dict()}

        if self.config.knowledge_graph_enabled:
            report["knowledge_graph"] = self.knowledge_graph.doctor()
        if self.config.event_engine_enabled:
            report["event_engine"] = self.event_engine.doctor()
        if self.config.scheduler_enabled:
            report["neuron_scheduler"] = self.neuron_scheduler.doctor()

        return report

    # ── Internal ─────────────────────────────────────────────

    @staticmethod
    def _build_summary(actions: list[dict[str, Any]]) -> str:
        parts = []
        for action in actions:
            atype = action.get("type", "unknown")
            if atype == "event_engine_scan":
                n = action.get("tasks_created", 0)
                parts.append(f"{n} tareas generadas desde eventos")
            elif atype == "neuron_schedule":
                n = action.get("wakeup_count", 0)
                parts.append(f"{n} neuronas programadas")
            elif atype == "knowledge_graph_maintenance":
                c = action.get("contradictions_found", 0)
                parts.append(f"{c} contradicciones detectadas")
        return "; ".join(parts) if parts else "sin acciones"


# ── Global singleton ─────────────────────────────────────────

_triadeos: TriadeOS | None = None


def get_triadeos(db_path: str | Path = "triade/memory/triade.db") -> TriadeOS:
    global _triadeos
    if _triadeos is None:
        _triadeos = TriadeOS(db_path=db_path)
    return _triadeos


def configure_triadeos(config: TriadeOSConfig, db_path: str | Path = "triade/memory/triade.db") -> TriadeOS:
    global _triadeos
    _triadeos = TriadeOS(db_path=db_path, config=config)
    return _triadeos

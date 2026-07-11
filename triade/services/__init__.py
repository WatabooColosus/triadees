"""Servicios internos de runtime local de Tríade."""

from .event_bus import build_context_from_events, list_recent_events, mark_event_processed, publish_event
from .supervisor import InternalRuntimeSupervisor

# Compatibilidad de contador: cuando el gobernador permite planear pero no
# nutrir neuronas, la planificación sigue siendo trabajo real y debe reflejarse
# en tasks_planned.
_original_governed_mission_service = InternalRuntimeSupervisor._governed_mission_service


def _counted_governed_mission_service(self, mode, governor):
    result = _original_governed_mission_service(self, mode, governor)
    planned = result.get("planned") if isinstance(result, dict) else None
    if planned and not result.get("nutrition"):
        self.counters["tasks_planned"] += len(planned)
    return result


InternalRuntimeSupervisor._governed_mission_service = _counted_governed_mission_service

__all__ = [
    "build_context_from_events",
    "list_recent_events",
    "mark_event_processed",
    "publish_event",
    "InternalRuntimeSupervisor",
]

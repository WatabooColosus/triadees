"""Servicios internos de runtime local de Tríade."""

from .event_bus import build_context_from_events, list_recent_events, mark_event_processed, publish_event
from .supervisor import InternalRuntimeSupervisor

# Compatibilidad operativa: cuando el gobernador permite workers pero no
# nutrición basada en modelo, el supervisor puede ejecutar la ruta local segura.
# `run_neuron_nutrition_cycle` decide si existe una misión activa elegible; si no,
# degrada a observe_only sin registrar ejecución falsa.
_original_governed_mission_service = InternalRuntimeSupervisor._governed_mission_service


def _safe_governed_mission_service(self, mode, governor):
    if not governor.get("can_run_workers", False):
        return _original_governed_mission_service(self, mode, governor)
    if not governor.get("can_nourish_neurons", False):
        return self._mission_service(mode)
    return _original_governed_mission_service(self, mode, governor)


InternalRuntimeSupervisor._governed_mission_service = _safe_governed_mission_service

__all__ = [
    "build_context_from_events",
    "list_recent_events",
    "mark_event_processed",
    "publish_event",
    "InternalRuntimeSupervisor",
]

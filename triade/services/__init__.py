"""Servicios internos de runtime local de Tríade."""

from .event_bus import build_context_from_events, list_recent_events, mark_event_processed, publish_event
from .supervisor import InternalRuntimeSupervisor


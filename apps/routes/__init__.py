"""Tríade Ω — Route handlers y normalizadores de contrato público."""

from . import api as api
from .api import _legacy_heartbeat_truth, _legacy_ollama_status

__all__ = ["api", "_legacy_heartbeat_truth", "_legacy_ollama_status"]

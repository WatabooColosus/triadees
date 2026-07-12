"""Federación entre nodos autorizados de Tríade Omega."""

from .federation import Federation
from .registry import FederatedNodeIdentity, FederatedNodeRegistry, VALID_PERMISSIONS, VALID_STATES

__all__ = [
    "Federation",
    "FederatedNodeIdentity",
    "FederatedNodeRegistry",
    "VALID_PERMISSIONS",
    "VALID_STATES",
]

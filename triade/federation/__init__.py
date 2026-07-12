"""Federación entre nodos autorizados de Tríade Omega."""

from .dispatch import FederatedDispatcher, FederatedWorkBudget
from .evidence_gate import FederatedEvidenceGate
from .exchange import FederatedEnvelope, FederatedExchangeStore, HMACEnvelopeAuthenticator
from .federation import Federation
from .registry import FederatedNodeIdentity, FederatedNodeRegistry, VALID_PERMISSIONS, VALID_STATES

__all__ = [
    "Federation",
    "FederatedDispatcher",
    "FederatedEnvelope",
    "FederatedEvidenceGate",
    "FederatedExchangeStore",
    "FederatedNodeIdentity",
    "FederatedNodeRegistry",
    "FederatedWorkBudget",
    "HMACEnvelopeAuthenticator",
    "VALID_PERMISSIONS",
    "VALID_STATES",
]

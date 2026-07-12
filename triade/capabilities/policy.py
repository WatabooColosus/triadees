"""Políticas operativas para capacidades registradas."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .registry import CapabilityRegistry

VALID_ACTIONS = {"read", "write", "execute", "promote"}


@dataclass(frozen=True, slots=True)
class CapabilityDecision:
    allowed: bool
    capability_id: str
    version: str | None
    action: str
    reason: str
    capability: dict[str, Any] | None = None


class CapabilityPolicyGuard:
    """Autoriza operaciones según estado, permisos y contrato registrado."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.registry = CapabilityRegistry(db_path)

    def decide(self, capability_id: str, action: str, version: str | None = None) -> CapabilityDecision:
        if action not in VALID_ACTIONS:
            return CapabilityDecision(False, capability_id, version, action, "acción no soportada")

        capability = self.registry.get(capability_id, version)
        if capability is None:
            return CapabilityDecision(False, capability_id, version, action, "capacidad no registrada")

        state = str(capability.get("state") or "experimental")
        permissions = set(capability.get("permissions") or ())
        resolved_version = str(capability.get("version") or version or "")

        if state == "blocked":
            return CapabilityDecision(
                False,
                capability_id,
                resolved_version,
                action,
                "capacidad bloqueada",
                capability,
            )
        if action == "promote" and state == "deprecated":
            return CapabilityDecision(
                False,
                capability_id,
                resolved_version,
                action,
                "una capacidad deprecated no puede recibir promociones",
                capability,
            )
        if action not in permissions:
            return CapabilityDecision(
                False,
                capability_id,
                resolved_version,
                action,
                "permiso no concedido",
                capability,
            )
        return CapabilityDecision(True, capability_id, resolved_version, action, "permitido", capability)

    def require(self, capability_id: str, action: str, version: str | None = None) -> dict[str, Any]:
        decision = self.decide(capability_id, action, version)
        if not decision.allowed:
            raise PermissionError(f"{capability_id}:{action} rechazado: {decision.reason}")
        assert decision.capability is not None
        return decision.capability

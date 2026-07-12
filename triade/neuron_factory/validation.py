"""Validación de especificaciones contra el Capability Registry."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from triade.capabilities import CapabilityRegistry

from .specification import NeuronSpecification


@dataclass(frozen=True, slots=True)
class SpecificationValidationResult:
    valid: bool
    missing_capabilities: tuple[str, ...]
    blocked_capabilities: tuple[str, ...]
    deprecated_capabilities: tuple[str, ...]

    def require_valid(self) -> None:
        if self.valid:
            return
        reasons: list[str] = []
        if self.missing_capabilities:
            reasons.append(f"faltantes={','.join(self.missing_capabilities)}")
        if self.blocked_capabilities:
            reasons.append(f"bloqueadas={','.join(self.blocked_capabilities)}")
        if self.deprecated_capabilities:
            reasons.append(f"deprecated={','.join(self.deprecated_capabilities)}")
        raise ValueError("especificación incompatible con Capability Registry: " + "; ".join(reasons))


class NeuronSpecificationValidator:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.registry = CapabilityRegistry(db_path)

    def validate(self, specification: NeuronSpecification) -> SpecificationValidationResult:
        specification.validate()
        missing: list[str] = []
        blocked: list[str] = []
        deprecated: list[str] = []

        for capability_id in sorted(set(specification.requires_capabilities)):
            capability = self.registry.get(capability_id)
            if capability is None:
                missing.append(capability_id)
                continue
            state = str(capability.get("state") or "")
            if state == "blocked":
                blocked.append(capability_id)
            elif state == "deprecated":
                deprecated.append(capability_id)

        return SpecificationValidationResult(
            valid=not (missing or blocked or deprecated),
            missing_capabilities=tuple(missing),
            blocked_capabilities=tuple(blocked),
            deprecated_capabilities=tuple(deprecated),
        )

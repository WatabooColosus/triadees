"""Cola segura de instalación de modelos Ollama para Tríade Ω.

No descarga modelos directamente. Genera acciones recomendadas con estado,
razones, requisitos mínimos y comando sugerido. La ejecución real queda para una
fase posterior con autorización explícita.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .compatibility_matrix import ModelCompatibilityMatrix
from .hardware_profile import HardwareProfile


@dataclass(slots=True)
class ModelInstallCandidate:
    model: str
    status: str
    priority: int
    command: str
    reason: str
    estimated_ram_gb: float
    required_disk_free_gb: float
    warnings: list[str] = field(default_factory=list)
    authorized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModelInstallQueue:
    """Construye una cola de instalación segura para modelos recomendados."""

    DISK_BUFFER_GB = 8.0

    PRIORITY_BY_ROLE = {
        "embedding": 10,
        "hypothalamus": 20,
        "central": 30,
        "fast": 40,
        "coder": 50,
        "creator": 60,
        "trainer": 70,
        "deep": 80,
    }

    def __init__(self, hardware: HardwareProfile, available_models: list[str] | None = None) -> None:
        self.hardware = hardware
        self.available_models = available_models or []
        self.matrix = ModelCompatibilityMatrix(hardware=hardware, available_models=self.available_models)

    def build(self, include_allowed: bool = False) -> dict[str, Any]:
        matrix = self.matrix.build()
        candidates: list[ModelInstallCandidate] = []
        for item in matrix["models"]:
            if item["installed"]:
                continue
            if item["status"] == "blocked":
                continue
            if item["status"] == "risky":
                continue
            if item["status"] == "allowed" and not include_allowed:
                continue
            candidate = self._candidate_from_item(item)
            candidates.append(candidate)

        candidates.sort(key=lambda item: item.priority)
        return {
            "status": "ok",
            "mode": "install-queue",
            "policy": {
                "auto_install": False,
                "requires_authorization": True,
                "disk_buffer_gb": self.DISK_BUFFER_GB,
                "note": "La cola recomienda instalaciones; no ejecuta ollama pull automáticamente.",
            },
            "hardware": self.hardware.to_dict(),
            "available_models": self.available_models,
            "count": len(candidates),
            "candidates": [item.to_dict() for item in candidates],
            "summary": self._summary(candidates),
        }

    def _candidate_from_item(self, item: dict[str, Any]) -> ModelInstallCandidate:
        roles = item.get("recommended_roles") or []
        priority = min((self.PRIORITY_BY_ROLE.get(role, 99) for role in roles), default=99)
        estimated_ram = float(item.get("estimated_ram_gb") or 4.0)
        required_disk = round(max(estimated_ram * 1.8, 3.0) + self.DISK_BUFFER_GB, 2)
        warnings = list(item.get("warnings") or [])
        if self.hardware.disk_free_gb and self.hardware.disk_free_gb < required_disk:
            warnings.append("Disco libre insuficiente para instalación segura.")
        reason = ", ".join(item.get("reasons") or []) or "Modelo compatible recomendado por matriz."
        return ModelInstallCandidate(
            model=str(item["model"]),
            status="pending_authorization",
            priority=priority,
            command=f"ollama pull {item['model']}",
            reason=reason,
            estimated_ram_gb=estimated_ram,
            required_disk_free_gb=required_disk,
            warnings=warnings,
            authorized=False,
        )

    @staticmethod
    def _summary(candidates: list[ModelInstallCandidate]) -> str:
        if not candidates:
            return "No hay modelos recomendados pendientes de instalación."
        return f"Hay {len(candidates)} modelo(s) recomendados para instalar con autorización."

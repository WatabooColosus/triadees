"""CognitiveLoad — Mide la carga cognitiva del sistema.

Calcula carga compuesta de CPU, RAM, GPU, tareas pendientes, errores recientes.
También provee señales de curiosidad, incertidumbre y fatiga por componente.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from triade.hypothalamus.senses import SystemSnapshot


@dataclass(frozen=True, slots=True)
class CognitiveSnapshot:
    """Resultado del cálculo de carga cognitiva."""
    overall_load: float = 0.0
    cpu_pressure: float = 0.0
    ram_pressure: float = 0.0
    gpu_pressure: float = 0.0
    task_pressure: float = 0.0
    error_pressure: float = 0.0
    curiosity: float = 0.0
    uncertainty: float = 0.0
    fatigue_cpu: float = 0.0
    fatigue_ram: float = 0.0
    fatigue_gpu: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_load": self.overall_load,
            "cpu_pressure": self.cpu_pressure,
            "ram_pressure": self.ram_pressure,
            "gpu_pressure": self.gpu_pressure,
            "task_pressure": self.task_pressure,
            "error_pressure": self.error_pressure,
            "curiosity": self.curiosity,
            "uncertainty": self.uncertainty,
            "fatigue_cpu": self.fatigue_cpu,
            "fatigue_ram": self.fatigue_ram,
            "fatigue_gpu": self.fatigue_gpu,
        }


class CognitiveLoad:
    """Calcula la carga cognitiva del sistema basada en señales de hardware."""

    # Pesos para la carga compuesta
    WEIGHTS = {
        "cpu": 0.25,
        "ram": 0.20,
        "gpu": 0.25,
        "tasks": 0.15,
        "errors": 0.15,
    }

    # Umbrales de presión
    THRESHOLDS = {
        "low": 0.3,
        "medium": 0.6,
        "high": 0.8,
        "critical": 0.95,
    }

    @classmethod
    def compute(cls, snapshot: SystemSnapshot) -> CognitiveSnapshot:
        """Calcula la carga cognitiva completa desde un snapshot del sistema."""
        cpu_pressure = snapshot.cpu_load
        ram_pressure = snapshot.ram_usage
        gpu_pressure = max(snapshot.gpu_utilization, snapshot.gpu_memory_used)

        # Presión de tareas: normalizada (1 tarea = 0.1, 10+ = 1.0)
        task_pressure = min(1.0, snapshot.pending_tasks * 0.1)

        # Presión de errores: tasa de errores directa
        error_pressure = snapshot.error_rate_hour

        # Carga compuesta ponderada
        overall = (
            cls.WEIGHTS["cpu"] * cpu_pressure
            + cls.WEIGHTS["ram"] * ram_pressure
            + cls.WEIGHTS["gpu"] * gpu_pressure
            + cls.WEIGHTS["tasks"] * task_pressure
            + cls.WEIGHTS["errors"] * error_pressure
        )
        overall = round(min(1.0, overall), 4)

        # Fatiga por componente: cuánto tiempo lleva en alto uso
        # (esto se actualiza acumulativamente en el EmotionalState)
        fatigue_cpu = cls._component_fatigue(cpu_pressure)
        fatigue_ram = cls._component_fatigue(ram_pressure)
        fatigue_gpu = cls._component_fatigue(gpu_pressure)

        return CognitiveSnapshot(
            overall_load=overall,
            cpu_pressure=round(cpu_pressure, 4),
            ram_pressure=round(ram_pressure, 4),
            gpu_pressure=round(gpu_pressure, 4),
            task_pressure=round(task_pressure, 4),
            error_pressure=round(error_pressure, 4),
            curiosity=0.0,  # Se calcula externamente con contexto de la query
            uncertainty=0.0,  # Se calcula externamente con historial de confianza
            fatigue_cpu=fatigue_cpu,
            fatigue_ram=fatigue_ram,
            fatigue_gpu=fatigue_gpu,
        )

    @classmethod
    def compute_with_context(
        cls,
        snapshot: SystemSnapshot,
        query_novelty: float = 0.5,
        recent_confidence: float = 0.7,
    ) -> CognitiveSnapshot:
        """Calcula carga cognitiva con contexto de la query para curiosidad e incertidumbre."""
        base = cls.compute(snapshot)
        # Curiosidad: basada en novedad de la query (0.0 = conocida, 1.0 = completamente nueva)
        curiosity = round(_clamp(query_novelty * 0.8 + base.overall_load * 0.2), 4)
        # Incertidumbre: inversa de la confianza reciente, amplificada por carga
        uncertainty = round(_clamp((1.0 - recent_confidence) * 0.7 + base.overall_load * 0.3), 4)

        return CognitiveSnapshot(
            overall_load=base.overall_load,
            cpu_pressure=base.cpu_pressure,
            ram_pressure=base.ram_pressure,
            gpu_pressure=base.gpu_pressure,
            task_pressure=base.task_pressure,
            error_pressure=base.error_pressure,
            curiosity=curiosity,
            uncertainty=uncertainty,
            fatigue_cpu=base.fatigue_cpu,
            fatigue_ram=base.fatigue_ram,
            fatigue_gpu=base.fatigue_gpu,
        )

    @staticmethod
    def _component_fatigue(pressure: float) -> float:
        """Calcula fatiga de un componente basada en su presión actual.

        Fatiga crece exponencialmente con la presión:
        - pressure < 0.3: fatiga baja (~0.1)
        - pressure 0.6: fatiga media (~0.4)
        - pressure > 0.8: fatiga alta (~0.8+)
        """
        if pressure < 0.1:
            return 0.0
        # Función exponencial suave
        fatigue = pressure ** 1.5
        return round(min(1.0, fatigue), 4)

    @classmethod
    def pressure_level(cls, load: float) -> str:
        """Retorna el nivel de presión: low, medium, high, critical."""
        if load >= cls.THRESHOLDS["critical"]:
            return "critical"
        if load >= cls.THRESHOLDS["high"]:
            return "high"
        if load >= cls.THRESHOLDS["medium"]:
            return "medium"
        return "low"

    @classmethod
    def should_reduce_workload(cls, snapshot: SystemSnapshot) -> bool:
        """Determina si el sistema debería reducir carga de trabajo."""
        cognitive = cls.compute(snapshot)
        return (
            cognitive.overall_load > 0.8
            or cognitive.cpu_pressure > 0.9
            or cognitive.gpu_pressure > 0.9
            or cognitive.error_pressure > 0.3
        )

    @classmethod
    def should_enter_rest_mode(cls, snapshot: SystemSnapshot) -> bool:
        """Determina si el sistema debería entrar en modo descanso."""
        cognitive = cls.compute(snapshot)
        return (
            cognitive.overall_load > 0.95
            or (cognitive.cpu_pressure > 0.95 and cognitive.ram_pressure > 0.9)
            or snapshot.gpu_temperature > 85
        )


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))

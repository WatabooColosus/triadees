"""Core Alignment · auditoría de órganos internos de Tríade Ω.

Evalúa si Central, Hipotálamo, Bodega, Cristal y Runner cumplen la teoría
operativa mínima declarada en el proyecto.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class OrganAlignment:
    organ: str
    score: float
    status: str
    fulfilled: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CoreAlignment:
    """Diagnóstico teórico-técnico del núcleo Tríade."""

    EXPECTED_ARTIFACTS = {
        "input.json",
        "signals.json",
        "memory.json",
        "crystal.json",
        "plan.json",
        "safety.json",
        "output.json",
        "memory_diff.json",
        "report.json",
        "integrity.json",
        "CLOSED",
    }

    def evaluate_static_core(self) -> dict[str, Any]:
        organs = [
            self.evaluate_central(),
            self.evaluate_hypothalamus(),
            self.evaluate_bodega(),
            self.evaluate_crystal(),
            self.evaluate_runner(),
        ]
        average = round(sum(item.score for item in organs) / len(organs), 2)
        return {
            "status": self._status_from_score(average),
            "score": average,
            "organs": [item.to_dict() for item in organs],
            "summary": self._summary(average),
        }

    def evaluate_run_artifacts(self, artifacts: list[str]) -> dict[str, Any]:
        present = set(artifacts)
        missing = sorted(self.EXPECTED_ARTIFACTS - present)
        extra = sorted(present - self.EXPECTED_ARTIFACTS)
        score = round((len(self.EXPECTED_ARTIFACTS) - len(missing)) / len(self.EXPECTED_ARTIFACTS), 2)
        return {
            "status": self._status_from_score(score),
            "score": score,
            "present": sorted(present),
            "missing": missing,
            "extra": extra,
        }

    def evaluate_central(self) -> OrganAlignment:
        return OrganAlignment(
            organ="central",
            score=0.65,
            status="partial",
            fulfilled=[
                "Crea PlanPacket.",
                "Recibe señales, memoria y cristal.",
                "Genera OutputPacket.",
                "Usa Ollama o fallback por plantilla.",
            ],
            missing=[
                "Planificación dinámica profunda.",
                "Uso automático de Model Router.",
                "Gobierno activo de aprendizaje controlado.",
                "Integración de N Creadora/N Formadora en el ciclo principal.",
            ],
            recommendations=[
                "Implementar Central Autonomy 1.8.",
                "Conectar Model Router al Runner si no se fijan modelos manuales.",
            ],
        )

    def evaluate_hypothalamus(self) -> OrganAlignment:
        return OrganAlignment(
            organ="hypothalamus",
            score=0.75,
            status="operational",
            fulfilled=[
                "Detecta intención, tono, urgencia y riesgo.",
                "Genera PV-7.",
                "Usa modelo local o fallback por reglas.",
                "Valida JSON de señales del modelo.",
            ],
            missing=[
                "Estado emocional longitudinal.",
                "Personalidad dinámica por neurona.",
                "Aprendizaje afectivo desde historial.",
            ],
            recommendations=[
                "Crear Emotional State 2.2.",
                "Persistir señales emocionales agregadas por sesión.",
            ],
        )

    def evaluate_bodega(self) -> OrganAlignment:
        return OrganAlignment(
            organ="bodega",
            score=0.82,
            status="strong",
            fulfilled=[
                "Inicializa SQLite.",
                "Recupera identidad y memoria episódica/semántica básica.",
                "Guarda runs, episodios, señales, cristal, safety, reportes y modelos.",
                "Expone doctor con conteos y tablas.",
            ],
            missing=[
                "Embeddings reales para memoria semántica.",
                "Learning queue activo.",
                "Backups automáticos y rotación de runs.",
            ],
            recommendations=[
                "Implementar Semantic Memory 1.9.",
                "Implementar Learning Queue 1.8.",
                "Implementar Backup/Health 2.0.",
            ],
        )

    def evaluate_crystal(self) -> OrganAlignment:
        return OrganAlignment(
            organ="crystal",
            score=0.60,
            status="partial",
            fulfilled=[
                "Regula ética, profundidad, creatividad y relación.",
                "Calcula pv7_score, stability e intensity.",
                "Ajusta respuesta ante riesgo alto o memoria baja.",
            ],
            missing=[
                "Fórmula Q_cristal completa.",
                "Campos propios para pv7_score, stability e intensity en CrystalPacket y SQLite.",
                "Historial temporal del Cristal.",
            ],
            recommendations=[
                "Implementar Crystal v2 1.8.",
                "Migrar CrystalPacket y crystal_states con métricas extendidas.",
            ],
        )

    def evaluate_runner(self) -> OrganAlignment:
        return OrganAlignment(
            organ="runner",
            score=0.88,
            status="strong",
            fulfilled=[
                "Ejecuta ciclo input → señales → memoria → cristal → plan → safety → salida.",
                "Guarda artefactos JSON por run.",
                "Cierra runs con integrity.json y CLOSED.",
                "Registra eventos de modelo.",
            ],
            missing=[
                "Selección automática de modelos por Model Router.",
                "Ejecución de aprendizaje controlado post-run.",
            ],
            recommendations=[
                "Implementar Model Router Auto Runner 1.7B.",
                "Agregar post-run learning candidate opcional.",
            ],
        )

    @staticmethod
    def _status_from_score(score: float) -> str:
        if score >= 0.85:
            return "strong"
        if score >= 0.70:
            return "operational"
        if score >= 0.50:
            return "partial"
        return "weak"

    @staticmethod
    def _summary(score: float) -> str:
        if score >= 0.85:
            return "El núcleo está muy alineado con la teoría operativa."
        if score >= 0.70:
            return "El núcleo está funcional y parcialmente alineado; faltan capas avanzadas."
        if score >= 0.50:
            return "El núcleo representa la teoría, pero requiere refuerzo estructural."
        return "El núcleo aún no sostiene la teoría mínima."

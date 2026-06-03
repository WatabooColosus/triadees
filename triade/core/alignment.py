"""Core Alignment · auditoría de órganos internos de Tríade Ω.

Evalúa si Central, Hipotálamo, Bodega, Cristal y Runner cumplen la teoría
operativa mínima declarada en el proyecto.

Desde Fase A.3 (cierre de D-03) la evaluación estática es *dinámica*: cada
capacidad se comprueba por introspección real del código (métodos presentes,
campos de contratos, integración entre órganos) en vez de puntajes fijos. Así
`align` deja de afirmar como "pendiente" lo que ya está implementado.
"""

from __future__ import annotations

import inspect
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


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


def _safe(predicate: Callable[[], bool]) -> bool:
    """Evalúa una comprobación sin permitir que align falle por una excepción."""
    try:
        return bool(predicate())
    except Exception:
        return False


def _source(obj: Any) -> str:
    try:
        return inspect.getsource(obj)
    except Exception:
        return ""


def _init_params(cls: Any) -> set[str]:
    try:
        return set(inspect.signature(cls.__init__).parameters)
    except Exception:
        return set()


class CoreAlignment:
    """Diagnóstico teórico-técnico del núcleo Tríade (medido, no declarado)."""

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
            "mode": "dynamic-code-introspection",
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

    # ------------------------------------------------------------------
    # Evaluación por órgano (cada check es una comprobación real de código)
    # ------------------------------------------------------------------

    @staticmethod
    def _build(organ: str, checks: list[tuple[str, bool]], recommendations: list[str]) -> OrganAlignment:
        fulfilled = [label for label, ok in checks if ok]
        missing = [label for label, ok in checks if not ok]
        score = round(len(fulfilled) / len(checks), 2) if checks else 0.0
        if score >= 0.85:
            status = "strong"
        elif score >= 0.70:
            status = "operational"
        elif score >= 0.50:
            status = "partial"
        else:
            status = "weak"
        active_recs = [rec for rec in recommendations if missing]
        return OrganAlignment(
            organ=organ,
            score=score,
            status=status,
            fulfilled=fulfilled,
            missing=missing,
            recommendations=active_recs,
        )

    def evaluate_central(self) -> OrganAlignment:
        from .central import Central

        plan_src = _source(getattr(Central, "plan", None))
        runner_run_src = self._runner_run_source()
        checks = [
            ("Genera plan cognitivo (Central.plan).", _safe(lambda: hasattr(Central, "plan"))),
            ("Genera salida (Central.respond).", _safe(lambda: hasattr(Central, "respond"))),
            ("Usa modelo local con fallback por plantilla.", "model_client" in _init_params(Central)),
            ("Respeta gobernanza semántica al planear.", "governance" in plan_src),
            ("Integra N Creadora/Formadora en el ciclo run().", "neuron" in runner_run_src.lower()),
        ]
        return self._build(
            "central",
            checks,
            [
                "Conectar NeuronCreator/NeuronTrainer al ciclo run() (gobierno de aprendizaje).",
                "Ver Fase B del ROADMAP para la integración de órganos existentes.",
            ],
        )

    def evaluate_hypothalamus(self) -> OrganAlignment:
        from .hypothalamus import Hypothalamus

        rules_src = _source(getattr(Hypothalamus, "_analyze_rules", None))
        virtues = ["humildad", "generosidad", "respeto", "paciencia", "templanza", "caridad", "diligencia"]
        pv7_complete = all(virtue in rules_src for virtue in virtues)
        checks = [
            ("Detecta intención, tono, urgencia y riesgo (analyze).", _safe(lambda: hasattr(Hypothalamus, "analyze"))),
            ("Genera vector PV-7 completo (7 ejes).", pv7_complete),
            ("Usa modelo local con fallback por reglas.", "model_client" in _init_params(Hypothalamus)),
            ("Valida el JSON de señales del modelo.", _safe(lambda: hasattr(Hypothalamus, "_parse_model_json"))),
            ("Mantiene estado emocional longitudinal por sesión.", "session" in rules_src.lower()),
        ]
        return self._build(
            "hypothalamus",
            checks,
            ["Persistir señales emocionales agregadas por sesión (estado longitudinal)."],
        )

    def evaluate_bodega(self) -> OrganAlignment:
        from .bodega import Bodega

        schema_src = self._read("triade/memory/schemas.sql")
        store_methods = ["store_signal", "store_crystal", "store_safety", "store_verification_report", "store_episode"]
        persists_all = all(hasattr(Bodega, method) for method in store_methods)
        semantic_ok = _safe(self._semantic_layer_importable)
        governance_ok = _safe(self._semantic_governance_importable)
        learning_active = "learning_queue" in self._learning_code_refs()
        checks = [
            ("Inicializa SQLite con esquema versionado.", _safe(lambda: hasattr(Bodega, "_init_db"))),
            ("Persiste señales, cristal, safety, episodios y reportes.", persists_all),
            ("Expone diagnóstico (doctor).", _safe(lambda: hasattr(Bodega, "doctor"))),
            ("Memoria semántica vectorial operativa (store/search/embedding).", semantic_ok),
            ("Gobernanza semántica de estados (candidate→stable).", governance_ok),
            ("Cola de aprendizaje (learning_queue) con lógica activa.", learning_active and "learning_queue" in schema_src),
        ]
        return self._build(
            "bodega",
            checks,
            [
                "Implementar el Learning Pipeline sobre learning_queue (Fase C del ROADMAP).",
                "Reutilizar la gobernanza semántica como motor de consolidación.",
            ],
        )

    def evaluate_crystal(self) -> OrganAlignment:
        from .crystal import Crystal
        from .contracts import CrystalPacket

        try:
            packet_fields = set(CrystalPacket.__dataclass_fields__)
        except Exception:
            packet_fields = set()
        v2_metrics = {"pv7_score", "stability", "intensity", "q_crystal"}.issubset(packet_fields)
        temporal_fields = {"temporal_status", "q_delta", "stability_delta", "history_window"}.issubset(packet_fields)
        context_fields = {"context_scope", "context_key", "comparison_basis"}.issubset(packet_fields)
        checks = [
            ("Regula ética, profundidad, creatividad y relación (regulate).", _safe(lambda: hasattr(Crystal, "regulate"))),
            ("Fórmula Q_cristal relacional completa (q_crystal_payload).", _safe(lambda: hasattr(Crystal, "q_crystal_payload"))),
            ("Métricas extendidas en CrystalPacket (pv7/stability/intensity/Q).", v2_metrics),
            ("Continuidad temporal (temporal_state + deltas).", _safe(lambda: hasattr(Crystal, "temporal_state")) and temporal_fields),
            ("Historial comparativo contextualizado.", context_fields),
        ]
        return self._build(
            "crystal",
            checks,
            ["Crystal v2 ya implementado; mantener trazabilidad de la ventana temporal."],
        )

    def evaluate_runner(self) -> OrganAlignment:
        run_src = self._runner_run_source()
        init_src = self._runner_init_source()
        writes_all_artifacts = all(name in run_src for name in self.EXPECTED_ARTIFACTS)
        checks = [
            ("Ejecuta el ciclo cognitivo completo (run).", bool(run_src)),
            ("Escribe los 11 artefactos auditables por run.", writes_all_artifacts),
            ("Cierra el run con integrity.json y CLOSED.", "integrity.json" in run_src and "CLOSED" in run_src),
            ("Selección automática de modelos (Model Router).", "ModelRouter" in init_src or "_select_models" in init_src),
            ("Registra eventos y calidad de modelo por run.", "store_model_event" in run_src),
            ("Ejecuta aprendizaje controlado post-run.", "learning" in run_src.lower()),
        ]
        return self._build(
            "runner",
            checks,
            ["Agregar paso opcional de candidato de aprendizaje post-run (Fase C del ROADMAP)."],
        )

    # ------------------------------------------------------------------
    # Sondas de bajo nivel (todas tolerantes a fallo)
    # ------------------------------------------------------------------

    @staticmethod
    def _runner_run_source() -> str:
        try:
            from .runner import TriadeRunner

            return _source(TriadeRunner.run)
        except Exception:
            return ""

    @staticmethod
    def _runner_init_source() -> str:
        try:
            from .runner import TriadeRunner

            return _source(TriadeRunner.__init__) + _source(getattr(TriadeRunner, "_select_models", None))
        except Exception:
            return ""

    @staticmethod
    def _semantic_layer_importable() -> bool:
        from triade.memory.semantic_search import SemanticSearchEngine  # noqa: F401
        from triade.memory.semantic_store import SemanticMemoryStore  # noqa: F401

        return True

    @staticmethod
    def _semantic_governance_importable() -> bool:
        from triade.memory.semantic_governance import SemanticMemoryGovernance  # noqa: F401

        return True

    @staticmethod
    def _learning_code_refs() -> str:
        """Concatena el código que *debería* operar la cola de aprendizaje.

        Hoy ningún módulo referencia learning_queue, por lo que esta sonda
        devuelve vacío y el check correspondiente queda como pendiente real.
        """
        return ""

    @staticmethod
    def _read(path: str) -> str:
        try:
            from pathlib import Path

            return Path(path).read_text(encoding="utf-8")
        except Exception:
            return ""

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

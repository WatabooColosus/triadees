"""Reflexion interna del nucleo de Triade.

Convierte metricas observadas en propuestas verificables. Por defecto es
read-only; solo registra neuronas candidatas cuando se pide explicitamente.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .conversation_analyzer import ConversationAnalyzer
from .neuron_creator import NeuronCreator, NeuronSpec
from .neuron_registry import NeuronRegistry
from .neuron_trainer import NeuronTrainer


@dataclass(slots=True)
class SelfReflectionEngine:
    """Metacognicion verificable para observar, proponer y preparar mejoras."""

    db_path: str | Path = "triade/memory/triade.db"

    def reflect(
        self,
        limit: int = 50,
        since: str | None = None,
        source: str | None = None,
        register_neuron_candidates: bool = False,
    ) -> dict[str, Any]:
        analyzer = ConversationAnalyzer(db_path=self.db_path)
        analysis = analyzer.analyze(limit=limit, since=since, source=source)
        observations = self._observations(analysis)
        proposals = self._neuron_proposals(analysis, observations)
        registered = []
        if register_neuron_candidates:
            registered = self._register_neuron_candidates(proposals)
        return {
            "status": "ok",
            "mode": "self_reflection",
            "policy": {
                "identity_core_modified": False,
                "auto_learning_consolidation": False,
                "auto_code_modification": False,
                "neuron_registration": "candidate_only" if register_neuron_candidates else "proposal_only",
                "auto_approve_for_activation": True,
            },
            "filters": analysis["filters"],
            "core_awareness": {
                "knows_what_happened": self._coverage_ok(analysis),
                "knows_why_partially": True,
                "knows_model_use": analysis["model_usage"]["total_events"] > 0,
                "knows_memory_state": True,
                "limitations": self._limitations(analysis),
            },
            "observations": observations,
            "neuron_proposals": [proposal["spec"] for proposal in proposals],
            "neuron_assessments": [proposal["assessment"] for proposal in proposals],
            "registered_neuron_candidates": registered,
            "learning_candidates": analysis["learning_candidates"],
            "self_improvement_loop": self._self_improvement_loop(analysis, observations, proposals),
            "required_human_decisions": self._required_human_decisions(proposals),
            "source_analysis": analysis,
        }

    def export_markdown(self, payload: dict[str, Any], path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_markdown(payload), encoding="utf-8")
        return target

    def to_markdown(self, payload: dict[str, Any]) -> str:
        lines = [
            "# Triade Self Improvement Path",
            "",
            "Reflexion interna generada desde datos locales. No modifica identidad, no consolida aprendizaje y no cambia codigo automaticamente.",
            "",
            "## Estado",
            "",
            f"- Modo: {payload['policy']['neuron_registration']}",
            f"- Sabe que ocurrio: {payload['core_awareness']['knows_what_happened']}",
            f"- Sabe uso de modelos: {payload['core_awareness']['knows_model_use']}",
            "",
            "## Observaciones",
            "",
        ]
        lines.extend(f"- {item}" for item in payload["observations"])
        lines.extend(["", "## Neuronas Propuestas", ""])
        for spec in payload["neuron_proposals"]:
            lines.extend([
                f"### {spec['name']}",
                "",
                f"- Dominio: {spec['domain']}",
                f"- Mision: {spec['mission']}",
                "- Estado: candidate",
                "",
            ])
        lines.extend(["## Ciclo Real", ""])
        for step in payload["self_improvement_loop"]:
            lines.append(f"- {step['stage']}: {step['objective']} | criterio: {step['acceptance']}")
        lines.extend(["", "## Decisiones Humanas Requeridas", ""])
        lines.extend(f"- {item}" for item in payload["required_human_decisions"])
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _coverage_ok(analysis: dict[str, Any]) -> bool:
        traceability = analysis.get("traceability", {})
        return all(float(item.get("coverage_percent", 0.0)) >= 95.0 for item in traceability.values())

    @staticmethod
    def _observations(analysis: dict[str, Any]) -> list[str]:
        summary = analysis["summary"]
        model_usage = analysis["model_usage"]
        crystal = analysis["crystal_evolution"]
        patterns = analysis["conversation_patterns"]
        observations = [
            f"Runs analizados: {summary['runs_analyzed']} con cobertura de trazabilidad completa si cada etapa supera 95%.",
            f"Uso de modelos: {model_usage['fallback_percent']}% fallback/failed y {model_usage['ollama_percent']}% Ollama ok.",
            f"Cristal promedio: Q={crystal['avg_q_crystal']} estabilidad={crystal['avg_stability']}.",
        ]
        semantic_total = sum(int(value) for value in summary["semantic_counts"].values())
        if semantic_total == 0:
            observations.append("Memoria semantica local sin documentos/embeddings analizados; la continuidad depende sobre todo de memoria episodica.")
        if model_usage["fallback_percent"] >= 35:
            observations.append("Fallback alto: el nucleo necesita diagnostico fino de modelos y causas de caida.")
        if patterns["recurring_warnings"]:
            observations.append("Hay advertencias recurrentes que pueden alimentar una neurona verificadora.")
        if crystal["degradation_count"] > 0:
            observations.append("Hay degradaciones o deltas negativos de Cristal que requieren seguimiento temporal.")
        return observations

    def _neuron_proposals(self, analysis: dict[str, Any], observations: list[str]) -> list[dict[str, Any]]:
        proposals: list[NeuronSpec] = []
        model_usage = analysis["model_usage"]
        summary = analysis["summary"]
        patterns = analysis["conversation_patterns"]
        crystal = analysis["crystal_evolution"]

        if model_usage["fallback_percent"] >= 35:
            proposals.append(self._create_spec(
                name="neurona_diagnostico_modelos",
                domain="model-router",
                mission="Observar eventos de modelo, separar causas de fallback y recomendar rutas Central/Hipotalamo verificables.",
                rules=[
                    "No cambiar modelos activos sin aprobacion humana.",
                    "Registrar causa de fallback con evidencia de model_events.",
                    "Comparar calidad por rol, modelo, fuente e intencion.",
                ],
            ))

        if sum(int(value) for value in summary["semantic_counts"].values()) == 0:
            proposals.append(self._create_spec(
                name="neurona_memoria_semantica",
                domain="memory",
                mission="Detectar conversaciones o documentos que merecen pasar a candidatos de memoria semantica sin consolidarlos automaticamente.",
                rules=[
                    "No escribir identity_core.",
                    "Solo proponer learning_queue con source_ref y riesgo bajo o medio.",
                    "Rechazar datos privados no verificados.",
                ],
            ))

        if patterns["recurring_warnings"]:
            proposals.append(self._create_spec(
                name="neurona_verificadora_recurrente",
                domain="verification",
                mission="Agrupar advertencias recurrentes de verification_reports y proponer pruebas o controles para reducirlas.",
                rules=[
                    "Trabajar sobre verification_reports agregados.",
                    "No ocultar advertencias por conveniencia.",
                    "Cada mejora propuesta debe incluir test esperado.",
                ],
            ))

        recurring = set(patterns["recurring_themes"].keys())
        if {"nombre", "llames", "camila"} & recurring:
            proposals.append(self._create_spec(
                name="neurona_continuidad_conversacional",
                domain="conversation",
                mission="Cuidar continuidad conversacional y preferencias recordables sin convertir inferencias privadas en identidad estable.",
                rules=[
                    "Distinguir preferencia conversacional, memoria episodica e identidad nucleo.",
                    "No consolidar nombres o relaciones sin aprobacion explicita.",
                    "Señalar cuando una memoria es candidata y no hecho estable.",
                ],
            ))

        if crystal["degradation_count"] > 0:
            proposals.append(self._create_spec(
                name="neurona_guardiana_cristal",
                domain="crystal",
                mission="Monitorear degradaciones de Q_crystal y estabilidad para sugerir ajustes de prudencia, memoria y verificacion.",
                rules=[
                    "Usar solo crystal_states y signal_states como evidencia.",
                    "No alterar formula del Cristal sin prueba y documento tecnico.",
                    "Recomendar umbrales y tests antes de implementar cambios.",
                ],
            ))

        proposals.append(self._create_spec(
            name="neurona_arquitecta_core",
            domain="core-architecture",
            mission="Mantener el backlog del nucleo, dividir modulos grandes y preparar cambios incrementales compatibles con CLI, API y UI.",
            rules=[
                "No tocar federacion salvo bloqueo directo del nucleo.",
                "Cada refactor debe conservar tests existentes.",
                "Preferir cambios pequenos con documento tecnico o test.",
            ],
        ))
        trainer = NeuronTrainer()
        return [{"spec": spec.to_dict(), "assessment": trainer.evaluate(spec).to_dict()} for spec in proposals]

    @staticmethod
    def _create_spec(name: str, domain: str, mission: str, rules: list[str]) -> NeuronSpec:
        spec = NeuronCreator().create(name=name, mission=mission, domain=domain, rules=rules)
        spec.status = "candidate"
        spec.created_by = "self_reflection"
        return spec

    def _register_neuron_candidates(self, proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        registry = NeuronRegistry(db_path=self.db_path)
        registered = []
        for proposal in proposals:
            raw = proposal["spec"]
            spec = NeuronSpec(
                name=raw["name"],
                mission=raw["mission"],
                domain=raw["domain"],
                rules=list(raw.get("rules") or []),
                status="candidate",
                created_by="self_reflection",
            )
            neuron_id = registry.register(spec)
            registered.append({"neuron_id": neuron_id, "name": spec.name, "status": "candidate"})
        return registered

    @staticmethod
    def _self_improvement_loop(
        analysis: dict[str, Any],
        observations: list[str],
        proposals: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        return [
            {
                "stage": "observe",
                "objective": "Leer runs, model_events, crystal_states, verification_reports y memoria sin modificar DB estable.",
                "acceptance": "Salida JSON contiene politica read-only y trazabilidad por etapa.",
            },
            {
                "stage": "analyze",
                "objective": f"Convertir {analysis['summary']['runs_analyzed']} runs en metricas de fallback, Cristal, fuentes e intenciones.",
                "acceptance": "Métricas reproducibles por analyze-conversations y reflect-core.",
            },
            {
                "stage": "propose",
                "objective": f"Proponer {len(proposals)} neuronas candidatas segun necesidades observadas.",
                "acceptance": "Cada neurona tiene mision, dominio, reglas, assessment y estado candidate.",
            },
            {
                "stage": "test",
                "objective": "Definir prueba esperada antes de activar o usar una neurona en el ciclo cognitivo.",
                "acceptance": "La neurona no pasa a experimental/stable sin test o evidencia.",
            },
            {
                "stage": "verify",
                "objective": "Verificar que la mejora no reduce trazabilidad, seguridad ni compatibilidad CLI/API/UI.",
                "acceptance": "pytest, doctor y reporte de reflexion pasan.",
            },
            {
                "stage": "approve",
                "objective": "Pedir aprobacion humana para consolidar learning, activar neuronas o modificar codigo.",
                "acceptance": "No hay consolidacion automatica ni cambios de identidad.",
            },
            {
                "stage": "integrate",
                "objective": "Integrar cambios pequenos y reversibles al nucleo.",
                "acceptance": "Nuevo estado queda documentado y auditable.",
            },
        ]

    @staticmethod
    def _required_human_decisions(proposals: list[dict[str, Any]]) -> list[str]:
        names = ", ".join(proposal["spec"]["name"] for proposal in proposals)
        return [
            f"Decidir si registrar/activar estas neuronas candidatas: {names}.",
            "Aprobar explicitamente cualquier consolidacion en memoria semantica estable.",
            "Aprobar cambios de codigo que permitan auto-mejora ejecutiva.",
            "Definir umbral minimo para promover candidate -> experimental -> stable.",
        ]

    @staticmethod
    def _limitations(analysis: dict[str, Any]) -> list[str]:
        limitations = [
            "La reflexion observa metricas y propone; no demuestra conciencia humana.",
            "No ejecuta cambios de codigo ni instala capacidades por si sola.",
        ]
        if analysis["model_usage"]["fallback_percent"] > 0:
            limitations.append("Parte de los runs usaron fallback o modelos fallidos; la calidad comparativa aun es parcial.")
        if sum(int(value) for value in analysis["summary"]["semantic_counts"].values()) == 0:
            limitations.append("La memoria semantica local no contiene documentos/embeddings en la muestra actual.")
        return limitations


def add_reflect_core_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", default="triade/memory/triade.db", help="Ruta de base SQLite")
    parser.add_argument("--limit", type=int, default=50, help="Cantidad maxima de runs")
    parser.add_argument("--since", default=None, help="Fecha minima YYYY-MM-DD")
    parser.add_argument("--source", choices=["console", "single-port-ui", "test"], default=None, help="Filtra fuente")
    parser.add_argument("--json", action="store_true", help="Imprime JSON completo")
    parser.add_argument("--export", default=None, help="Exporta reporte Markdown")
    parser.add_argument(
        "--register-neuron-candidates",
        action="store_true",
        help="Registra propuestas como neuronas candidate; no las activa ni promueve.",
    )

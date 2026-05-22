"""Neurona Central · planeación y respuesta reguladas por Cristal."""

from __future__ import annotations

import json

from triade.models.ollama_client import OllamaClient

from .contracts import CrystalPacket, InputPacket, MemoryPacket, OutputPacket, PlanPacket, SignalPacket


class Central:
    """Planeador y generador de salida con regulación del Cristal Morfológico.

    Usa Ollama si está disponible y conserva fallback por plantilla si falla.
    Fase 1.8D: incorpora estado temporal del Cristal al plan y a la respuesta.
    """

    def __init__(self, model_client: OllamaClient | None = None, central_model: str = "qwen2.5:3b-instruct") -> None:
        self.model_client = model_client
        self.central_model = central_model

    def plan(
        self,
        input_packet: InputPacket,
        signals: SignalPacket,
        memory: MemoryPacket,
        crystal: CrystalPacket,
    ) -> PlanPacket:
        steps = [
            "Leer entrada del usuario.",
            "Usar señales del Hipotálamo.",
            "Consultar memoria disponible.",
            "Aplicar regulación del Cristal.",
            f"Evaluar continuidad temporal del Cristal: {crystal.temporal_status}.",
        ]

        if crystal.temporal_status in {"critical", "degrading"}:
            steps.append("Reforzar prudencia por degradación temporal y registrar alerta.")
        elif crystal.temporal_status == "improving":
            steps.append("Sostener mejora temporal sin exceder control ético ni trazabilidad.")

        if crystal.q_crystal < 0.40:
            steps.append("Responder con prudencia elevada y evitar decisiones expansivas.")
        elif crystal.q_crystal >= 0.70 and crystal.stability >= 0.65 and crystal.temporal_status not in {"critical", "degrading"}:
            steps.append("Profundizar la respuesta manteniendo trazabilidad y control ético.")
        else:
            steps.append("Producir respuesta verificable con regulación equilibrada.")

        tools: list[str] = []
        if signals.intent == "build_or_update":
            tools.append("repository_or_file_update")

        return PlanPacket(
            run_id=input_packet.run_id,
            goal=(
                f"Atender intención: {signals.intent} | q_crystal={crystal.q_crystal} "
                f"| temporal={crystal.temporal_status}"
            ),
            steps=steps,
            tools=tools,
            safety_required=True,
        )

    def respond(
        self,
        input_packet: InputPacket,
        signals: SignalPacket,
        memory: MemoryPacket,
        crystal: CrystalPacket,
        plan: PlanPacket,
    ) -> OutputPacket:
        identity = next(
            (item["value"] for item in memory.identity_matches if item.get("key") == "entity_name"),
            "Tríade Ω",
        )
        fallback_response = self._fallback_response(identity, input_packet, signals, crystal)
        temporal_action = "crystal_temporal_regulation_applied"

        if self.model_client is None:
            return OutputPacket(
                run_id=input_packet.run_id,
                response=fallback_response,
                actions_taken=["plan_created", "crystal_regulation_applied", temporal_action, "template_fallback_response_generated"],
                memory_diff={"pending_persistence": True},
                status="ok",
                model_provider="template",
                model_name="template-fallback",
                model_ok=False,
            )

        prompt = self._build_prompt(identity, input_packet, signals, memory, crystal, plan)
        system = (
            "Eres Tríade Ω, un sistema cognitivo modular en construcción verificable. "
            "Responde en español, con claridad, honestidad y tono útil. "
            "Aplica q_crystal y temporal_status: ante degradación o criticidad, prioriza prudencia, "
            "verificación y límites; ante mejora estable puedes profundizar sin inventar capacidades. "
            "Si algo es local, experimental o pendiente, dilo."
        )
        result = self.model_client.generate(self.central_model, prompt=prompt, system=system)

        if not result.ok or not result.text:
            return OutputPacket(
                run_id=input_packet.run_id,
                response=fallback_response,
                actions_taken=["plan_created", "crystal_regulation_applied", temporal_action, "ollama_failed", "template_fallback_response_generated"],
                memory_diff={"pending_persistence": True},
                status="ok",
                model_provider="ollama",
                model_name=self.central_model,
                model_ok=False,
                model_error=result.error,
            )

        return OutputPacket(
            run_id=input_packet.run_id,
            response=result.text,
            actions_taken=["plan_created", "crystal_regulation_applied", temporal_action, "ollama_response_generated"],
            memory_diff={"pending_persistence": True},
            status="ok",
            model_provider="ollama",
            model_name=self.central_model,
            model_ok=True,
        )

    @staticmethod
    def _fallback_response(identity: str, input_packet: InputPacket, signals: SignalPacket, crystal: CrystalPacket) -> str:
        mode = Central._crystal_mode(crystal)
        return (
            f"{identity} procesó el run {input_packet.run_id}. "
            f"Intención detectada: {signals.intent}. Riesgo: {signals.risk}. "
            f"Cristal: ética={crystal.ethics}, profundidad={crystal.depth}, "
            f"creatividad={crystal.creativity}, relación={crystal.relation}, "
            f"Q={crystal.q_crystal}, estabilidad={crystal.stability}. "
            f"Continuidad temporal: {crystal.temporal_status}, ΔQ={crystal.q_delta}, "
            f"Δestabilidad={crystal.stability_delta}. Regulación activa: {mode}. "
            "Ciclo cognitivo verificable completado."
        )

    @staticmethod
    def _crystal_mode(crystal: CrystalPacket) -> str:
        if crystal.temporal_status in {"critical", "degrading"}:
            return "prudencia temporal reforzada"
        if crystal.q_crystal < 0.40:
            return "prudencia elevada"
        if crystal.q_crystal >= 0.70 and crystal.stability >= 0.65:
            return "profundidad estable"
        return "equilibrio operativo"

    @staticmethod
    def _build_prompt(
        identity: str,
        input_packet: InputPacket,
        signals: SignalPacket,
        memory: MemoryPacket,
        crystal: CrystalPacket,
        plan: PlanPacket,
    ) -> str:
        memory_summary = {
            "identity": memory.identity_matches[:5],
            "episodic_matches": memory.episodic_matches[:3],
            "semantic_matches": memory.semantic_matches[:3],
            "confidence": memory.confidence,
        }
        payload = {
            "identity": identity,
            "user_input": input_packet.user_input,
            "signals": signals.to_dict(),
            "memory": memory_summary,
            "crystal": crystal.to_dict(),
            "crystal_mode": Central._crystal_mode(crystal),
            "temporal_alerts": crystal.temporal_alerts,
            "plan": plan.to_dict(),
        }
        return (
            "Procesa este paquete cognitivo de Tríade y responde al usuario. "
            "La regulación del Cristal y su continuidad temporal no son decorativas: "
            "úsalas para ajustar prudencia, profundidad y tono. Mantén la respuesta útil y verificable.\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )

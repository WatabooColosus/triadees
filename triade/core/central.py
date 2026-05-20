"""Neurona Central · MVP with optional Ollama generation."""

from __future__ import annotations

import json

from triade.models.ollama_client import OllamaClient

from .contracts import CrystalPacket, InputPacket, MemoryPacket, OutputPacket, PlanPacket, SignalPacket


class Central:
    """Planeador y generador de salida.

    Usa Ollama si está disponible y conserva fallback por plantilla si falla.
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
            "Producir respuesta verificable.",
        ]

        tools: list[str] = []
        if signals.intent == "build_or_update":
            tools.append("repository_or_file_update")

        return PlanPacket(
            run_id=input_packet.run_id,
            goal=f"Atender intención: {signals.intent}",
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

        if self.model_client is None:
            return OutputPacket(
                run_id=input_packet.run_id,
                response=fallback_response,
                actions_taken=["plan_created", "template_fallback_response_generated"],
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
            "No inventes capacidades: si algo es local, experimental o pendiente, dilo."
        )
        result = self.model_client.generate(self.central_model, prompt=prompt, system=system)

        if not result.ok or not result.text:
            return OutputPacket(
                run_id=input_packet.run_id,
                response=fallback_response,
                actions_taken=["plan_created", "ollama_failed", "template_fallback_response_generated"],
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
            actions_taken=["plan_created", "ollama_response_generated"],
            memory_diff={"pending_persistence": True},
            status="ok",
            model_provider="ollama",
            model_name=self.central_model,
            model_ok=True,
        )

    @staticmethod
    def _fallback_response(identity: str, input_packet: InputPacket, signals: SignalPacket, crystal: CrystalPacket) -> str:
        return (
            f"{identity} procesó el run {input_packet.run_id}. "
            f"Intención detectada: {signals.intent}. "
            f"Riesgo: {signals.risk}. "
            f"Cristal: ética={crystal.ethics}, profundidad={crystal.depth}, "
            f"creatividad={crystal.creativity}, relación={crystal.relation}. "
            "MVP operativo: ciclo cognitivo mínimo completado."
        )

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
            "plan": plan.to_dict(),
        }
        return (
            "Procesa este paquete cognitivo de Tríade y responde al usuario. "
            "Mantén la respuesta breve, útil y verificable.\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )

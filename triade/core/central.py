"""Neurona Central · MVP."""

from __future__ import annotations

from .contracts import CrystalPacket, InputPacket, MemoryPacket, OutputPacket, PlanPacket, SignalPacket


class Central:
    """Planeador y generador de salida mínima."""

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

        response = (
            f"{identity} procesó el run {input_packet.run_id}. "
            f"Intención detectada: {signals.intent}. "
            f"Riesgo: {signals.risk}. "
            f"Cristal: ética={crystal.ethics}, profundidad={crystal.depth}, "
            f"creatividad={crystal.creativity}, relación={crystal.relation}. "
            "MVP operativo: ciclo cognitivo mínimo completado."
        )

        return OutputPacket(
            run_id=input_packet.run_id,
            response=response,
            actions_taken=["plan_created", "response_generated"],
            memory_diff={"pending_persistence": True},
            status="ok",
        )

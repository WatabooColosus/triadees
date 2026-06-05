"""Neurona Central · planeación y respuesta reguladas por Cristal y memoria gobernada."""

from __future__ import annotations

import json

from triade.models.ollama_client import OllamaClient

from .contracts import CrystalPacket, InputPacket, MemoryPacket, OutputPacket, PlanPacket, SignalPacket


class Central:
    """Planeador y generador de salida con regulación del Cristal Morfológico.

    Usa Ollama si está disponible y conserva fallback por plantilla si falla.
    Desde 1.9E, solo recibe recuerdos semánticos autorizados por gobernanza y
    exige atribución literal de fuente/estado cuando la memoria se menciona.
    Desde 1.9F, separa el paquete cognitivo interno de la respuesta final: las
    métricas y señales solo se exponen cuando el usuario pide auditoría/debug.
    """

    INTERNAL_AUDIT_TERMS = {
        "audita",
        "auditoría",
        "auditoria",
        "analiza el run",
        "analiza este run",
        "diagnóstico técnico",
        "diagnostico tecnico",
        "debug",
        "trazabilidad",
        "q_crystal",
        "cristal",
        "hipotálamo",
        "hipotalamo",
        "pv7",
        "paquete cognitivo",
        "reporte interno",
        "señales internas",
        "senales internas",
    }

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
            "Consultar memoria disponible y respetar su gobierno de confianza.",
            "Aplicar regulación del Cristal.",
            f"Evaluar continuidad temporal del Cristal: {crystal.temporal_status}.",
        ]
        governance = memory.semantic_recall.get("governance", {})
        if int(governance.get("quarantined_vector_matches", 0) or 0) > 0:
            steps.append("Excluir memorias semánticas en cuarentena de cualquier afirmación factual.")
        if int(governance.get("allowed_vector_matches", 0) or 0) > 0:
            steps.append("Usar únicamente memoria semántica autorizada y conservar atribución literal.")
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
            goal=f"Atender intención: {signals.intent} | q_crystal={crystal.q_crystal} | temporal={crystal.temporal_status}",
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
        identity = next((item["value"] for item in memory.identity_matches if item.get("key") == "entity_name"), "Tríade Ω")
        wants_internal_audit = self._wants_internal_audit(input_packet.user_input)
        fallback_response = self._fallback_response(identity, input_packet, signals, crystal, wants_internal_audit)
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
        prompt = self._build_prompt(identity, input_packet, signals, memory, crystal, plan, wants_internal_audit)
        system = (
            "Eres Tríade Ω, un sistema cognitivo modular en construcción verificable. "
            "Responde en español, con claridad, honestidad y tono útil. "
            "El paquete cognitivo interno es contexto privado: no lo expliques, no lo resumas y no lo trates como tema de conversación. "
            "No menciones JSON, señales, plan, memoria interna, q_crystal, PV7, Cristal, Hipotálamo, continuidad temporal ni métricas internas, salvo que el usuario pida auditoría, debug o trazabilidad explícitamente. "
            "Usa q_crystal y temporal_status solo para regular prudencia, profundidad y tono. "
            "La memoria semántica incluida ya fue filtrada por gobernanza: usa solamente semantic_matches presentes. "
            "No inventes el origen de una memoria, proyecto, neurona, documento, fuente o estado. "
            "Si mencionas procedencia, usa únicamente source_ref, document_id, document_status o contexto literal del paquete. "
            "Si no hay memoria semántica autorizada suficiente, dilo en vez de completar con suposiciones. "
            "Para saludos, afecto o conversación casual, responde breve, humano y directo."
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
    def _fallback_response(
        identity: str,
        input_packet: InputPacket,
        signals: SignalPacket,
        crystal: CrystalPacket,
        wants_internal_audit: bool = False,
    ) -> str:
        if not wants_internal_audit:
            if Central._is_social_input(input_packet.user_input):
                return f"Hola, soy {identity}. Estoy contigo y listo para ayudarte."
            return f"{identity} recibió tu mensaje y lo atenderá con una respuesta clara y verificable."

        mode = Central._crystal_mode(crystal)
        return (
            f"{identity} procesó el run {input_packet.run_id}. "
            f"Intención detectada: {signals.intent}. Riesgo: {signals.risk}. "
            f"Cristal: ética={crystal.ethics}, profundidad={crystal.depth}, creatividad={crystal.creativity}, "
            f"relación={crystal.relation}, Q={crystal.q_crystal}, estabilidad={crystal.stability}. "
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

    @classmethod
    def _wants_internal_audit(cls, user_input: str) -> bool:
        text = user_input.lower()
        return any(term in text for term in cls.INTERNAL_AUDIT_TERMS)

    @staticmethod
    def _is_social_input(user_input: str) -> bool:
        text = user_input.lower().strip()
        social_terms = {
            "hola",
            "buenas",
            "buenos días",
            "buenos dias",
            "buenas tardes",
            "buenas noches",
            "como estas",
            "cómo estás",
            "que tal",
            "qué tal",
            "me caes bien",
            "gracias",
        }
        return text in social_terms or len(text.split()) <= 4 and any(term in text for term in social_terms)

    @staticmethod
    def _build_prompt(
        identity: str,
        input_packet: InputPacket,
        signals: SignalPacket,
        memory: MemoryPacket,
        crystal: CrystalPacket,
        plan: PlanPacket,
        wants_internal_audit: bool = False,
    ) -> str:
        memory_summary = {
            "identity": memory.identity_matches[:5],
            "episodic_matches": memory.episodic_matches[:3],
            "semantic_matches_authorized_only": memory.semantic_matches[:3],
            "semantic_recall_governance": memory.semantic_recall.get("governance", {}),
            "confidence": memory.confidence,
        }
        payload = {
            "identity": identity,
            "user_input": input_packet.user_input,
            "input_context": input_packet.context,
            "signals": signals.to_dict(),
            "memory": memory_summary,
            "crystal": crystal.to_dict(),
            "crystal_mode": Central._crystal_mode(crystal),
            "temporal_alerts": crystal.temporal_alerts,
            "plan": plan.to_dict(),
            "response_mode": "internal_audit" if wants_internal_audit else "user_conversation",
        }
        if wants_internal_audit:
            instruction = (
                "El usuario pidió auditoría, debug o trazabilidad. Puedes explicar señales, Cristal, memoria, plan y continuidad temporal de forma estructurada, "
                "pero sin inventar procedencias ni hechos no presentes en el paquete."
            )
        else:
            instruction = (
                "Responde directamente al usuario final. El paquete cognitivo es privado y solo sirve para regular la respuesta. "
                "No lo describas, no lo audites, no enumeres pasos internos y no menciones métricas internas. "
                "Si la entrada es saludo, afecto o conversación casual, responde breve, cercano y natural. "
                "Usa únicamente `semantic_matches_authorized_only` como recuerdos semánticos disponibles si son relevantes. "
                "Los recuerdos en cuarentena son solo evidencia de control y no hechos para responder."
            )
        return instruction + "\n\nPAQUETE_INTERNO_PRIVADO:\n" + json.dumps(payload, ensure_ascii=False, indent=2)

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
    Desde 1.9I, el plan y el paquete cognitivo quedan como contexto interno; la
    salida normal se genera con contexto mínimo para permitir aprendizaje sin
    filtrar razonamiento operativo.
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
            "Eres Tríade Ω. Responde en español al usuario final. "
            "La arquitectura interna regula tu respuesta, pero no es el tema salvo auditoría explícita. "
            "No resumas contexto, JSON, plan, señales, memoria interna ni métricas. "
            "Aprende del contexto autorizado y responde naturalmente según la pregunta."
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
            return f"Soy {identity}. Estoy listo para ayudarte con una respuesta clara."
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
    def _build_prompt(
        identity: str,
        input_packet: InputPacket,
        signals: SignalPacket,
        memory: MemoryPacket,
        crystal: CrystalPacket,
        plan: PlanPacket,
        wants_internal_audit: bool = False,
    ) -> str:
        if not wants_internal_audit:
            safe_matches: list[dict[str, str]] = []
            for item in memory.semantic_matches[:3]:
                content = str(item.get("content", "")).strip()[:400]
                source_ref = str(item.get("source_ref") or item.get("document_id") or "memoria_autorizada")
                if content:
                    safe_matches.append({"source_ref": source_ref, "content": content})
            semantic_context = ""
            if safe_matches:
                semantic_context = "\nMemoria autorizada útil, si aplica:\n" + json.dumps(safe_matches, ensure_ascii=False, indent=2)
            return (
                "MODO RESPUESTA FINAL.\n"
                "Responde solo al usuario, de forma natural.\n"
                "No expliques el proceso interno, no hagas resumen de contexto, no muestres plan ni métricas.\n"
                "Puedes usar memoria autorizada como contexto si ayuda directamente.\n\n"
                f"Identidad: {identity}\n"
                f"Usuario dijo: {input_packet.user_input}\n"
                f"Intención orientativa: {signals.intent}\n"
                f"Tono orientativo: {signals.tone}\n"
                f"Riesgo orientativo: {signals.risk}\n"
                f"{semantic_context}\n\n"
                "Respuesta final:"
            )

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
            "response_mode": "internal_audit",
        }
        return (
            "MODO: AUDITORIA_INTERNA_SOLICITADA.\n"
            "El usuario pidió auditoría, debug o trazabilidad. Puedes explicar señales, Cristal, memoria, plan y continuidad temporal de forma estructurada, "
            "pero sin inventar procedencias ni hechos no presentes en el paquete.\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )

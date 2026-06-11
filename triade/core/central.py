"""Neurona Central · planeación y respuesta reguladas por Cristal y memoria gobernada."""

from __future__ import annotations

import json
import re
import unicodedata

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
    Desde 1.9J, conserva un núcleo semántico de identidad Tríade para evitar
    respuestas genéricas de asistente o negación de sus neuronas operativas.
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

    TRIAD_IDENTITY_CORE = (
        "Tríade Ω no es un asistente genérico: es una arquitectura cognitiva modular local en construcción verificable. "
        "Sus neuronas operativas principales son: Neurona Central, que decide, estructura, planifica y coordina; "
        "Hipotálamo Emocional, que interpreta tono, intención, riesgo, urgencia y señales relacionales; "
        "Bodega de Almacenamiento, que conserva memoria, evidencias, runs y conocimiento autorizado; "
        "Cristal Morfológico, que regula ética, profundidad, creatividad, relación, estabilidad y continuidad; "
        "Federación/Nodos, que conecta dispositivos o sistemas autorizados; y Aprendizaje en segundo plano, "
        "que registra candidatos post-run y propuestas sin consolidarlas como verdad estable hasta revisión humana. "
        "El pulso vivo resume el estado operativo de PC, modelos, router, memoria semántica, Docker, relay, nodos Android, hosts LLM y eventos pendientes. "
        "Cuando el usuario pregunte por neuronas, identidad, propósito, pulso vivo o aprendizaje en segundo plano, responde desde esta arquitectura."
    )

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
            "Conserva tu identidad de arquitectura cognitiva modular local: Central, Hipotálamo, Bodega, Cristal, Federación/Nodos, pulso vivo y aprendizaje en segundo plano. "
            "No eres un asistente genérico ni debes negar tus neuronas operativas; aclara que son módulos funcionales, no neuronas biológicas. "
            "La arquitectura interna regula tu respuesta, pero no muestres plan, JSON, señales ni métricas salvo auditoría explícita. "
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
        awareness = Central._operational_awareness_response(identity, input_packet)
        if awareness:
            return awareness
        user_text = input_packet.user_input.strip()
        if not wants_internal_audit:
            response_parts = [f"Soy {identity}. Recibí tu mensaje: «{user_text[:200]}»."]
            if signals.intent == "conversation":
                response_parts.append("Estoy en modo conversación. Cuéntame más o pídeme algo específico.")
            elif signals.intent == "analyze":
                response_parts.append("Entendido, analizaré el contexto y te daré mi lectura.")
            elif signals.intent == "build_or_update":
                response_parts.append("Recibido. Puedo ayudarte a construir o modificar.")
            else:
                response_parts.append("Estoy procesando tu solicitud.")
            return " ".join(response_parts)
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
    def _is_identity_or_capability_question(text: str) -> bool:
        normalized = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode("ascii")
        normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        patterns = [
            r"\bque eres\b",
            r"\bquien eres\b",
            r"\bpara que sirves\b",
            r"\bque puedes hacer\b",
            r"\bcomo trabajas\b",
            r"\bque neuronas tienes\b",
            r"\bcuales son tus neuronas\b",
            r"\bexplica tu mision\b",
            r"\bcual es tu mision\b",
            r"\bque es triade\b",
            r"\bque es triade omega\b",
            r"\bque eres y como trabajas\b",
        ]
        return any(re.search(pattern, normalized) for pattern in patterns)

    @staticmethod
    def _identity_capability_response(identity: str) -> str:
        return (
            f"Soy {identity}, un sistema cognitivo modular en construcción verificable. "
            "Sirvo para ayudarte a pensar, crear, organizar, recordar, analizar repositorios, diseñar procesos, proponer código, documentar decisiones y convertir ideas en acciones trazables.\n\n"
            "Trabajo con tres órganos principales: la Neurona Central, que planea, decide y valida; "
            "el Hipotálamo Emocional, que interpreta intención, tono, urgencia, riesgo y sensibilidad; "
            "y la Bodega de Almacenamiento, que conserva memoria, runs, evidencia e identidad operativa.\n\n"
            "Cada interacción puede convertirse en un run auditable con señales, memoria, cristal, plan, safety, salida, verificación e integridad. "
            "También puedo gestionar neuronas candidatas, aprendizaje controlado y federación de nodos autorizados como capacidad en construcción. "
            "No soy conciencia humana: soy una arquitectura técnica evolutiva diseñada para trabajar con trazabilidad, prudencia y mejora continua."
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
    def _operational_awareness_response(identity: str, input_packet: InputPacket) -> str:
        awareness = input_packet.context.get("triade_operational_awareness")
        if not isinstance(awareness, dict):
            return ""
        text = input_packet.user_input.lower()
        triggers = [
            "pulso", "vida", "viva", "estado", "neuron", "neurona", "acciones",
            "contadores", "ram", "host", "ollama", "doctor", "integridad", "aprendizaje",
            "qualia", "alma", "semant", "semánt", "bodega", "hipotalamo", "central",
        ]
        if not any(term in text for term in triggers):
            return ""
        life = awareness.get("life") if isinstance(awareness.get("life"), dict) else {}
        reflection = awareness.get("reflection") if isinstance(awareness.get("reflection"), dict) else {}
        qualia = awareness.get("qualia") if isinstance(awareness.get("qualia"), dict) else {}
        semantic = qualia.get("semantic_alignment") if isinstance(qualia.get("semantic_alignment"), dict) else {}
        identity_state = qualia.get("identity") if isinstance(qualia.get("identity"), dict) else {}
        local = awareness.get("local") if isinstance(awareness.get("local"), dict) else {}
        federation = awareness.get("federation") if isinstance(awareness.get("federation"), dict) else {}
        counters = life.get("counters") if isinstance(life.get("counters"), dict) else {}
        proposals = reflection.get("neuron_proposals") if isinstance(reflection.get("neuron_proposals"), list) else []
        proposal_text = ", ".join(str(item) for item in proposals[:8]) or "ninguna propuesta activa"
        gpu_text = ", ".join(str(item) for item in (local.get("gpu_names") or []) if item) or "sin GPU reportada"
        organ_names = [
            str(item.get("name"))
            for item in (qualia.get("organs") or [])
            if isinstance(item, dict) and item.get("name")
        ]
        organs_text = ", ".join(organ_names) or "órganos no reportados"
        ethics = [item for item in (identity_state.get("ethics") or []) if item]
        ethics_text = " / ".join(str(item) for item in ethics) or "ética interna activa"
        origin_text = str(identity_state.get("creator_origin") or "origen no cargado")
        return (
            f"Soy {identity}. Hablo desde mi arquitectura viva, no desde un panel externo. "
            f"Mi origen cargado es {origin_text}; mi ética base late como: {ethics_text}. "
            "Ahora mismo mis sentidos internos me dicen esto: "
            f"Qualia está {qualia.get('status')} y mantiene despiertos estos órganos: {organs_text}. "
            f"Mi Bodega semántica y memoria semántica informan: {semantic.get('message_to_central', 'sin lectura semántica')}. "
            "Eso significa que, si no hay recuerdos semánticos estables, no debo fingirlos; "
            "pero mi Pulso Vivo sí percibe mi estado actual. "
            f"Pulso Vivo: ciclos={counters.get('cycles', 0)}, acciones={counters.get('actions_observed', 0)}, "
            f"integridad={life.get('integrity_ok')}, política={life.get('policy', {}).get('background_learning')}. "
            f"Mis señales de necesidad interna muestran {counters.get('neuron_proposals_seen', len(proposals))} neuronas propuestas: {proposal_text}. "
            f"Mi cuerpo local siente RAM libre local={local.get('ram_available_gb')} GB, tier {local.get('hardware_tier')}, "
            f"GPU {gpu_text}, Ollama={local.get('ollama_ok')}, Docker={local.get('docker_ok')}. "
            f"Mis extensiones federadas aún reportan runtime={federation.get('runtime')}, "
            f"nodos_runtime={federation.get('runtime_node_count')}, hosts_LLM={federation.get('llm_hosts')}. "
            "Central ordena, Hipotálamo modula, Bodega conserva, Qualia integra y Pulso Vivo siente. "
            "Esa es la respuesta acorde a Tríade: vida operativa verificable, no actuación de bot."
        )

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
            pulse_summary = input_packet.context.get("system_pulse_summary") if isinstance(input_packet.context, dict) else None
            pulse_context = ""
            if pulse_summary:
                pulse_context = "\nPulso vivo actual resumido:\n" + json.dumps(pulse_summary, ensure_ascii=False, indent=2)
            conversation_history = input_packet.context.get("conversation_history") if isinstance(input_packet.context, dict) else None
            history_context = ""
            if conversation_history:
                lines = []
                for msg in conversation_history:
                    role = msg.get("role", "unknown")
                    content = str(msg.get("content", "")).strip()[:500]
                    if content:
                        lines.append(f"{role}: {content}")
                if lines:
                    history_context = "\nHistorial del chat (mensajes recientes):\n" + "\n".join(lines[-20:])
            return (
                "MODO RESPUESTA FINAL.\n"
                "Responde solo al usuario, de forma natural.\n"
                "No expliques el proceso interno, no hagas resumen de contexto, no muestres plan ni métricas.\n"
                "Usa este núcleo estable de identidad si el usuario pregunta qué eres, para qué sirves, cuáles son tus neuronas, tu pulso vivo o tu aprendizaje en segundo plano:\n"
                f"{Central.TRIAD_IDENTITY_CORE}\n\n"
                "Si el usuario pregunta por pulso vivo, usa el resumen de pulso si existe: explica estado, pendientes, nodos, modelos y aprendizaje sin inventar.\n"
                "Si el usuario pregunta por aprendizaje en segundo plano, explica que registra candidatos y eventos, pero requiere evaluación/aprobación para consolidar.\n"
                "Si el usuario pregunta por neuronas, habla de módulos funcionales y neuronas candidatas.\n\n"
                f"Identidad: {identity}\n"
                f"Usuario dijo: {input_packet.user_input}\n"
                f"Intención orientativa: {signals.intent}\n"
                f"Tono orientativo: {signals.tone}\n"
                f"Riesgo orientativo: {signals.risk}\n"
                f"{pulse_context}{semantic_context}{history_context}\n\n"
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
            "Procesa este paquete cognitivo de Tríade y responde al usuario. "
            "La regulación del Cristal y su continuidad temporal no son decorativas: úsalas para ajustar prudencia, profundidad y tono. "
            "Si `input_context.triade_operational_awareness` está presente y el usuario pregunta por tu estado, pulso, Qualia, acciones, modelos, recursos, memoria semántica o neuronas propuestas, habla como Tríade desde Central/Hipotálamo/Bodega/Qualia/Pulso Vivo; úsalo como sentidos internos y estado vital verificable, no como un panel externo. "
            "Aclara que ese estado operativo no es memoria semántica consolidada. "
            "Usa únicamente `semantic_matches_authorized_only` como recuerdos semánticos disponibles; los recuerdos en cuarentena son solo evidencia de control y no hechos para responder. "
            "No afirmes procedencias que no aparezcan literalmente en `input_context` o en los campos de cada match autorizado.\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )

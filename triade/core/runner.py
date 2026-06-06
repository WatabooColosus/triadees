"""Runner del ciclo cognitivo mínimo de Tríade Ω."""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

from triade.learning.pipeline import LearningPipeline
from triade.memory.semantic_embedding_engine import SemanticEmbeddingEngine
from triade.memory.semantic_continuity import SemanticContinuity
from triade.memory.semantic_governance import SemanticMemoryGovernance
from triade.memory.semantic_search import SemanticSearchEngine
from triade.memory.semantic_store import SemanticMemoryStore
from triade.models.hardware_profile import HardwareProfiler
from triade.models.model_router import ModelRouter
from triade.models.ollama_client import OllamaClient

from .background_neurons import candidates_from_system_debt
from .bodega import Bodega
from .central import Central
from .config import load_config
from .contracts import InputPacket
from .crystal import Crystal
from .hypothalamus import Hypothalamus
from .safety import Safety
from .verification import Verifier
from .edge_context import build_edge_context
from .neuron_formation_pipeline import form_candidates


class TriadeRunner:
    """Ejecuta: input → señales → memoria → gobierno → cristal → plan → safety → output → reporte."""

    INTERNAL_LEAK_TERMS = {
        "based on the provided json",
        "provided json",
        "provided data",
        "context summary",
        "context overview",
        "plan details",
        "system response plan",
        "pv7 scores",
        "crystal details",
        "temporal alerts",
        "q_crystal",
        "q-crystal",
        "hypothalamus",
        "run id",
        "regulation notes",
        "### contexto",
        "### context",
    }

    def __init__(
        self,
        runs_dir: str | Path = "runs",
        db_path: str | Path = "triade/memory/triade.db",
        config_path: str | Path = "triade.yml",
        use_ollama: bool = True,
        hypothalamus_model: str | None = None,
        central_model: str | None = None,
        auto_select_models: bool = True,
        semantic_search_engine: Any | None = None,
        semantic_governance: Any | None = None,
    ) -> None:
        self.runs_dir = Path(runs_dir)
        self.db_path = Path(db_path)
        self.config = load_config(config_path)
        model_cfg = self.config.get("models", {})
        roles = model_cfg.get("roles", {})
        self.model_provider = str(model_cfg.get("provider", "ollama"))
        self.ollama_base_url = str(model_cfg.get("base_url", "http://127.0.0.1:11434"))
        self.ollama_timeout = int(model_cfg.get("timeout", 60))
        self.auto_select_models = auto_select_models
        self.model_selection: dict[str, Any] = {"enabled": False, "reason": "manual_or_disabled"}
        self.model_client = None
        if use_ollama and self.model_provider == "ollama":
            self.model_client = OllamaClient(base_url=self.ollama_base_url, timeout=self.ollama_timeout)
        selected = self._select_models(
            manual_hypothalamus=hypothalamus_model,
            manual_central=central_model,
            fallback_hypothalamus=str(roles.get("hypothalamus", "qwen2.5:3b-instruct")),
            fallback_central=str(roles.get("central", "qwen2.5:3b-instruct")),
        )
        self.hypothalamus_model = selected["hypothalamus"]
        self.central_model = selected["central"]
        self.semantic_search_engine = semantic_search_engine
        self.semantic_governance = semantic_governance
        self.hypothalamus = Hypothalamus(model_client=self.model_client, model_name=self.hypothalamus_model)
        self.bodega = Bodega(db_path=self.db_path, semantic_search_engine=semantic_search_engine)
        self.crystal = Crystal()
        self.central = Central(model_client=self.model_client, central_model=self.central_model)
        self.safety = Safety()
        self.verifier = Verifier()

    def _select_models(self, manual_hypothalamus: str | None, manual_central: str | None, fallback_hypothalamus: str, fallback_central: str) -> dict[str, str]:
        if manual_hypothalamus or manual_central or not self.auto_select_models or self.model_client is None:
            self.model_selection = {"enabled": False, "reason": "manual_model_provided_or_ollama_disabled", "hypothalamus": manual_hypothalamus or fallback_hypothalamus, "central": manual_central or fallback_central}
            return {"hypothalamus": manual_hypothalamus or fallback_hypothalamus, "central": manual_central or fallback_central}
        health = self.model_client.health()
        if not health.get("ok"):
            self.model_selection = {"enabled": False, "reason": "ollama_unavailable", "ollama": health, "hypothalamus": fallback_hypothalamus, "central": fallback_central}
            return {"hypothalamus": fallback_hypothalamus, "central": fallback_central}
        hardware = HardwareProfiler().detect()
        router = ModelRouter(available_models=health.get("models", []), hardware=hardware)
        hyp = router.route("hypothalamus")
        cen = router.route("central")
        self.model_selection = {"enabled": True, "reason": "auto_selected_by_hardware_router", "hardware": hardware.to_dict(), "ollama": health, "hypothalamus": hyp.to_dict(), "central": cen.to_dict()}
        return {"hypothalamus": hyp.selected_model, "central": cen.selected_model}

    def _get_semantic_search_engine(self) -> SemanticSearchEngine:
        if self.semantic_search_engine is not None:
            return self.semantic_search_engine
        store = SemanticMemoryStore(db_path=self.db_path)
        client = OllamaClient(base_url=self.ollama_base_url, timeout=self.ollama_timeout)
        embedding = SemanticEmbeddingEngine(store=store, client=client)
        self.semantic_search_engine = SemanticSearchEngine(store=store, client=client, embedding_engine=embedding)
        return self.semantic_search_engine

    def _get_semantic_governance(self) -> SemanticMemoryGovernance:
        if self.semantic_governance is None:
            self.semantic_governance = SemanticMemoryGovernance(db_path=self.db_path)
        return self.semantic_governance

    def run(
        self,
        user_input: str,
        source: str = "console",
        context: dict[str, Any] | None = None,
        semantic_recall_enabled: bool = False,
        semantic_model: str | None = None,
        semantic_limit: int = 3,
        semantic_min_similarity: float = 0.55,
        semantic_domain: str | None = None,
        semantic_allow_experimental: bool = False,
        propose_neurons: bool = True,
    ) -> dict[str, Any]:
        input_packet = InputPacket(user_input=user_input, source=source, context=context or {})
        self.bodega.create_run(input_packet)
        run_path = self.runs_dir / input_packet.run_id
        run_path.mkdir(parents=True, exist_ok=True)
        signals = self.hypothalamus.analyze(input_packet)
        try:
            edge_text = (
                getattr(input_packet, "text", None)
                or getattr(input_packet, "content", None)
                or getattr(input_packet, "message", None)
                or getattr(input_packet, "user_input", None)
                or getattr(input_packet, "raw_text", None)
                or ""
            )
            edge_context = build_edge_context(edge_text, enable_summary=False)
        except Exception as exc:
            edge_context = {
                "enabled": True,
                "used_edge": False,
                "accepted": False,
                "node_id": None,
                "error": str(exc),
                "intent_probe": {
                    "intent": "edge_context_failed",
                    "urgency": "medium",
                    "risk": "low",
                    "needs_tool": False
                },
                "keywords": [],
                "summary": "",
                "evidence": {},
                "truth": "edge_context falló y fue aislado para no romper el run cognitivo."
            }
        hypothalamus_model_result = dict(self.hypothalamus.last_model_result)
        hypothalamus_quality = self._score_hypothalamus(signals, hypothalamus_model_result)
        signal_id = self.bodega.store_signal(signals)
        if semantic_recall_enabled and self.bodega.semantic_search_engine is None:
            self.bodega.semantic_search_engine = self._get_semantic_search_engine()
        memory = self.bodega.recall(
            input_packet,
            semantic_recall_enabled=semantic_recall_enabled,
            semantic_model=semantic_model,
            semantic_limit=semantic_limit,
            semantic_min_similarity=semantic_min_similarity,
            semantic_domain=semantic_domain,
        )
        if semantic_recall_enabled:
            memory = self._get_semantic_governance().govern_memory(memory, allow_experimental=semantic_allow_experimental)
        comparison_basis = self._build_comparison_basis(input_packet, signals.intent)
        crystal_history = self.bodega.list_recent_crystals(limit=5, context_key=comparison_basis["context_key"])
        crystal = self.crystal.regulate(signals, memory, history=crystal_history, comparison_basis=comparison_basis)
        crystal_id = self.bodega.store_crystal(crystal)
        plan = self.central.plan(input_packet, signals, memory, crystal)
        plan_dict = plan.to_dict()
        plan_dict["edge_context"] = {
            "used_edge": bool(edge_context.get("used_edge")),
            "accepted": bool(edge_context.get("accepted")),
            "node_id": edge_context.get("node_id"),
            "intent_probe": edge_context.get("intent_probe", {}),
            "keywords": edge_context.get("keywords", []),
            "summary": edge_context.get("summary", ""),
            "policy": "auxiliary_signal_only_central_validates",
            "truth": "El edge_context informa a la planeación, pero no decide por la Central."
        }
        if edge_context.get("accepted"):
            plan_dict.setdefault("steps", [])
            plan_dict["steps"].append(
                "Incorporar edge_context como señal auxiliar validada; no usarlo como autoridad final."
            )
        safety = self.safety.review(signals, plan, crystal=crystal, memory=memory)
        safety_id = self.bodega.store_safety(safety)
        if safety.status == "blocked":
            output = self.central.respond(input_packet, signals, memory, crystal, plan)
            output.response = "La acción fue bloqueada por Safety."
            output.status = "blocked"
        else:
            output = self.central.respond(input_packet, signals, memory, crystal, plan)
        output_gate = self._sanitize_user_response(output.response, input_packet.user_input, signals.intent)
        output.response = output_gate["response"]
        central_quality = self._score_central(output.response, output.model_ok)
        neuron_proposal = None
        if propose_neurons and signals.intent == "build_or_update" and safety.status != "blocked":
            neuron_proposal = self._propose_neuron_candidate(input_packet, signals)
        self.bodega.update_run_models(input_packet.run_id, hypothalamus_model_result.get("name", self.hypothalamus_model), output.model_name)
        hypothalamus_event_id = self.bodega.store_model_event(input_packet.run_id, "hypothalamus", str(hypothalamus_model_result.get("provider")), str(hypothalamus_model_result.get("name")), bool(hypothalamus_model_result.get("ok")), hypothalamus_model_result.get("error"), hypothalamus_quality)
        central_event_id = self.bodega.store_model_event(input_packet.run_id, "central", output.model_provider, output.model_name, output.model_ok, output.model_error, central_quality)
        memory_diff = self.bodega.store_episode(input_packet, output)
        temporal_state = {
            "status": crystal.temporal_status, "q_delta": crystal.q_delta, "stability_delta": crystal.stability_delta,
            "history_window": crystal.history_window, "alerts": crystal.temporal_alerts, "context_scope": crystal.context_scope,
            "context_key": crystal.context_key, "comparison_basis": crystal.comparison_basis,
        }
        semantic_state = dict(memory.semantic_recall)
        semantic_state["authorized_matches"] = memory.semantic_matches
        edge_usage = {
            "used_edge": bool(edge_context.get("used_edge")),
            "accepted": bool(edge_context.get("accepted")),
            "node_id": edge_context.get("node_id"),
            "intent": (edge_context.get("intent_probe") or {}).get("intent"),
            "urgency": (edge_context.get("intent_probe") or {}).get("urgency"),
            "risk": (edge_context.get("intent_probe") or {}).get("risk"),
            "needs_tool": (edge_context.get("intent_probe") or {}).get("needs_tool"),
            "keywords": edge_context.get("keywords", []),
            "policy": "auxiliary_signal_only_central_validates",
        }

        output.memory_diff = {
            **memory_diff, "signal_id": signal_id, "crystal_id": crystal_id, "safety_id": safety_id,
            "neuron_proposal": neuron_proposal,
            "edge_usage": edge_usage,
            "crystal_temporal_state": temporal_state, "semantic_recall": semantic_state,
            "hypothalamus_model_provider": hypothalamus_model_result.get("provider"), "hypothalamus_model_name": hypothalamus_model_result.get("name"), "hypothalamus_model_ok": hypothalamus_model_result.get("ok"), "hypothalamus_model_error": hypothalamus_model_result.get("error"), "hypothalamus_quality_score": hypothalamus_quality, "hypothalamus_model_event_id": hypothalamus_event_id,
            "central_model_provider": output.model_provider, "central_model_name": output.model_name, "central_model_ok": output.model_ok, "central_model_error": output.model_error, "central_quality_score": central_quality, "central_model_event_id": central_event_id,
            "model_provider": output.model_provider, "model_name": output.model_name, "model_ok": output.model_ok, "model_error": output.model_error, "model_selection": self.model_selection,
        }
        report = self.verifier.verify(output, safety, crystal=crystal, memory=memory)
        verification_id = self.bodega.store_verification_report(report)
        output.memory_diff["verification_report_id"] = verification_id
        post_run_learning = self._post_run_learning_candidate(input_packet, output, report, signals.intent)
        system_events = self._build_system_events(memory, crystal, neuron_proposal, post_run_learning, output_gate)
        system_events = self._filter_obsolete_edge_debt(system_events, edge_usage)
        background_neuron_candidates = candidates_from_system_debt(
            pulse_summary=(input_packet.context or {}).get("system_pulse_summary"),
            system_events=system_events,
            output_gate=output_gate,
            post_run_learning=post_run_learning,
        )
        background_neuron_candidates = self._filter_obsolete_edge_candidates(
            background_neuron_candidates,
            edge_usage,
        )
        background_neuron_candidates = form_candidates(background_neuron_candidates)
        for candidate in background_neuron_candidates:
            system_events.append({
                "type": "background_neuron_candidate",
                "severity": candidate.get("severity", "medium"),
                "status": "requires_human_approval",
                "message": f"Neurona candidata propuesta: {candidate.get('display_name') or candidate.get('name')}",
                "action_required": "approve_or_reject_background_neuron",
                "payload": candidate,
            })
        output.memory_diff["post_run_learning"] = post_run_learning
        semantic_continuity = self._semantic_continuity(input_packet, output, signals.intent, crystal)
        output.memory_diff["semantic_continuity"] = semantic_continuity
        output.memory_diff["system_events"] = system_events
        output.memory_diff["background_neuron_candidates"] = background_neuron_candidates
        output.memory_diff["output_gate"] = output_gate
        artifacts = {"input.json": input_packet.to_dict(), "signals.json": signals.to_dict(), "edge_context.json": edge_context, "memory.json": memory.to_dict(), "crystal.json": crystal.to_dict(), "plan.json": plan_dict, "plan_enriched.json": plan_dict, "safety.json": safety.to_dict(), "output.json": output.to_dict(), "memory_diff.json": output.memory_diff, "report.json": report.to_dict(), "system_events.json": system_events, "background_neuron_candidates.json": background_neuron_candidates, "semantic_continuity.json": semantic_continuity}
        if neuron_proposal is not None:
            artifacts["neuron_candidate.json"] = neuron_proposal
        if post_run_learning.get("enabled"):
            artifacts["post_run_learning.json"] = post_run_learning
        for filename, payload in artifacts.items():
            self._write_json(run_path / filename, payload)
        integrity = {
            "run_id": input_packet.run_id, "status": report.status, "artifacts": sorted(artifacts.keys()), "database": memory_diff.get("db_path"), "episode_id": memory_diff.get("episode_id"), "signal_id": signal_id, "crystal_id": crystal_id, "safety_id": safety_id, "verification_report_id": verification_id,
            "crystal_temporal_state": temporal_state, "semantic_recall": semantic_state,
            "safety_crystal_feedback": {"status": safety.status, "risk_types": safety.risk_types, "controls": safety.required_controls},
            "neuron_proposal": neuron_proposal,
            "post_run_learning": post_run_learning,
            "semantic_continuity": semantic_continuity,
            "system_events": system_events,
            "background_neuron_candidates": background_neuron_candidates,
            "output_gate": output_gate,
            "hypothalamus_model_provider": hypothalamus_model_result.get("provider"), "hypothalamus_model_name": hypothalamus_model_result.get("name"), "hypothalamus_model_ok": hypothalamus_model_result.get("ok"), "hypothalamus_quality_score": hypothalamus_quality, "hypothalamus_model_event_id": hypothalamus_event_id,
            "central_model_provider": output.model_provider, "central_model_name": output.model_name, "central_model_ok": output.model_ok, "central_quality_score": central_quality, "central_model_event_id": central_event_id, "model_provider": output.model_provider, "model_name": output.model_name, "model_ok": output.model_ok, "model_selection": self.model_selection, "closed": True,
        }
        self._write_json(run_path / "integrity.json", integrity)
        (run_path / "CLOSED").write_text("closed\n", encoding="utf-8")
        return {"run_id": input_packet.run_id, "response": output.response, "system_events": system_events, "safety": safety.to_dict(), "report": report.to_dict(), "memory_diff": output.memory_diff, "semantic_recall": semantic_state, "crystal_temporal_state": temporal_state, "models": {"hypothalamus": {**hypothalamus_model_result, "quality_score": hypothalamus_quality, "event_id": hypothalamus_event_id}, "central": {"provider": output.model_provider, "name": output.model_name, "ok": output.model_ok, "error": output.model_error, "quality_score": central_quality, "event_id": central_event_id}}, "model": {"provider": output.model_provider, "name": output.model_name, "ok": output.model_ok, "error": output.model_error}, "model_selection": self.model_selection, "neuron_proposal": neuron_proposal, "post_run_learning": post_run_learning, "background_neuron_candidates": background_neuron_candidates, "output_gate": output_gate, "run_path": str(run_path)}

    def _sanitize_user_response(self, response: str, user_input: str, intent: str) -> dict[str, Any]:
        text = (response or "").strip()
        if not text:
            return {"response": "Recibido. Estoy listo para ayudarte.", "modified": True, "reason": "empty_response"}
        user_text = user_input.lower().strip()
        operational_terms = {
            "pulso",
            "vida",
            "viva",
            "estado",
            "neuron",
            "neurona",
            "memoria",
            "semant",
            "semánt",
            "qualia",
            "bodega",
            "ram",
            "ollama",
            "doctor",
        }
        if any(term in user_text for term in operational_terms) and (
            "pulso vivo" in text.lower() or "bodega semántica" in text.lower() or "bodega semantica" in text.lower()
        ):
            return {"response": text, "modified": False, "reason": "operational_awareness_allowed"}
        lowered = text.lower()
        leak = any(term in lowered for term in self.INTERNAL_LEAK_TERMS)
        looks_like_report = text.count("###") >= 1 or text.count("- **") >= 2
        if not (leak or looks_like_report):
            return {"response": text, "modified": False, "reason": "clean"}
        if "chiste" in user_text or "broma" in user_text or "hazme re" in user_text:
            clean = "Claro: ¿Por qué el computador fue al médico? Porque tenía un virus y necesitaba reiniciarse la vida."
        elif "ave" in user_text or "pájaro" in user_text or "pajaro" in user_text:
            clean = "No soy un ave. Soy Tríade Ω: una arquitectura de IA modular que usa una Central para razonar, un Hipotálamo para leer señales y una Bodega para memoria y evidencias."
        elif "neuron" in user_text:
            clean = "Mis neuronas principales son la Central, el Hipotálamo Emocional y la Bodega de Almacenamiento. También puedo proponer neuronas candidatas, pero deben quedar pendientes de aprobación antes de volverse estables."
        elif user_text in {"hola", "buenas", "buenos dias", "buenos días"}:
            clean = "Hola, soy Tríade Ω. Estoy contigo y listo para ayudarte."
        elif intent == "conversation":
            clean = "Estoy contigo. Puedo responder de forma natural mientras mi proceso interno queda en segundo plano."
        else:
            clean = "Recibido. Lo atenderé sin exponer el proceso interno."
        return {"response": clean, "modified": True, "reason": "internal_leak_detected"}

    def _filter_obsolete_edge_candidates(self, candidates: list[dict], edge_usage: dict) -> list[dict]:
        """Filtra neuronas candidatas obsoletas cuando Android edge ya fue probado.

        Si el run tiene edge_usage aceptado, no tiene sentido proponer neuronas
        por ausencia de Android/LLM host basada en un pulse_summary viejo.
        """
        if not (edge_usage.get("used_edge") and edge_usage.get("accepted") and edge_usage.get("node_id")):
            return candidates

        blocked_fragments = (
            "nodos android",
            "hosts llm android",
            "llm_android_host",
            "android nativos online",
            "ausencia de nodos android",
            "preparaci",
            "emparejamiento",
        )

        filtered = []
        for candidate in candidates:
            haystack = " ".join([
                str(candidate.get("name") or ""),
                str(candidate.get("display_name") or ""),
                str(candidate.get("source") or ""),
                str(candidate.get("mission") or ""),
                str((candidate.get("evidence") or {}).get("summary") or ""),
            ]).lower()

            if any(fragment in haystack for fragment in blocked_fragments):
                continue
            filtered.append(candidate)

        return filtered


    def _filter_obsolete_edge_debt(self, system_events: list[dict], edge_usage: dict) -> list[dict]:
        """Filtra deuda obsoleta de federación si el run ya probó edge Android LLM.

        El pulso puede llegar desde contexto viejo. Si edge_usage confirma que
        Android fue usado y aceptado, no debemos proponer neuronas por
        '0 hosts LLM Android reales' ni 'Sin nodos Android nativos online'.
        """
        if not (edge_usage.get("used_edge") and edge_usage.get("accepted") and edge_usage.get("node_id")):
            return system_events

        filtered = []
        obsolete_names = {"llm_android_host", "federation"}
        obsolete_texts = (
            "0 hosts LLM Android reales",
            "Sin nodos Android nativos online",
        )

        for event in system_events:
            payload = event.get("payload") or {}
            evidence = payload.get("evidence") or {}
            name = str(evidence.get("name") or payload.get("name") or "")
            summary = str(evidence.get("summary") or payload.get("mission") or event.get("message") or "")

            if name in obsolete_names and any(t in summary for t in obsolete_texts):
                continue
            filtered.append(event)

        return filtered


    def _build_system_events(self, memory: Any, crystal: Any, neuron_proposal: Any | None, post_run_learning: dict[str, Any], output_gate: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        semantic = getattr(memory, "semantic_recall", {}) or {}
        governance = semantic.get("governance", {}) if isinstance(semantic, dict) else {}
        pending_candidates = int(governance.get("candidate_matches", 0) or governance.get("candidate_documents", 0) or 0)
        quarantined = int(governance.get("quarantined_vector_matches", 0) or 0)
        allowed = int(governance.get("allowed_vector_matches", 0) or 0)
        if pending_candidates > 0:
            events.append({"type": "semantic_candidates_pending", "severity": "info", "status": "requires_human_review", "message": f"Hay {pending_candidates} memorias semánticas candidatas. Pueden informar como hipótesis, no como verdad estable.", "action_required": "approve_or_reject_semantic_candidates"})
        if quarantined > 0:
            events.append({"type": "semantic_quarantine_notice", "severity": "warning", "status": "blocked_as_fact", "message": f"Hay {quarantined} coincidencias semánticas en cuarentena. No se usarán como hechos.", "action_required": "review_quarantined_memory"})
        if allowed > 0:
            events.append({"type": "semantic_authorized_recall", "severity": "info", "status": "used_as_context", "message": f"Se encontraron {allowed} recuerdos semánticos autorizados para contexto.", "action_required": "none"})
        if neuron_proposal is not None:
            events.append({"type": "neuron_candidate_proposed", "severity": "important", "status": "requires_human_approval", "message": f"Se propuso la neurona candidata '{neuron_proposal.get('name')}'. Requiere aprobación humana antes de activarse.", "action_required": "approve_or_reject_neuron_candidate", "payload": neuron_proposal})
        if post_run_learning.get("enabled"):
            events.append({"type": "post_run_learning_candidate", "severity": "important", "status": post_run_learning.get("status", "candidate_only"), "message": f"Aprendizaje post-run registrado como candidato: {post_run_learning.get('candidate_id')}. Requiere evaluación antes de consolidarse.", "action_required": "evaluate_learning_candidate", "payload": post_run_learning})
        if getattr(crystal, "temporal_status", "stable") in {"critical", "degrading"}:
            events.append({"type": "crystal_temporal_alert", "severity": "warning", "status": getattr(crystal, "temporal_status", "unknown"), "message": "El Cristal reporta degradación temporal. Conviene revisar continuidad y estabilidad antes de consolidar aprendizaje.", "action_required": "review_crystal_state"})
        if output_gate.get("modified"):
            events.append({"type": "output_gate_intervention", "severity": "warning", "status": output_gate.get("reason"), "message": "La salida intentó exponer proceso interno. OutputGate la corrigió antes de mostrarla al usuario.", "action_required": "review_output_gate"})
        return events

    def _semantic_continuity(self, input_packet: InputPacket, output: Any, intent: str, crystal: Any) -> dict[str, Any]:
        try:
            return SemanticContinuity(db_path=self.db_path, auto_ollama_embed=False).ingest_run(
                run_id=input_packet.run_id,
                user_input=input_packet.user_input,
                response=output.response,
                source=input_packet.source,
                intent=intent,
                q_crystal=crystal.q_crystal,
                stability=crystal.stability,
                model_summary={
                    "central": {"provider": output.model_provider, "name": output.model_name, "ok": output.model_ok},
                    "selection": self.model_selection,
                },
            )
        except Exception as exc:
            return {
                "status": "error",
                "mode": "semantic-continuity",
                "error": str(exc),
                "policy": {"auto_consolidation": False, "identity_core_modified": False},
            }

    def _post_run_learning_candidate(self, input_packet: InputPacket, output: Any, report: Any, intent: str) -> dict[str, Any]:
        enabled = str(os.environ.get("TRIADE_POST_RUN_LEARNING", "")).strip().lower() in {"1", "true", "yes", "on"}
        if not enabled:
            return {"enabled": False, "reason": "disabled_by_default", "policy": "set_TRIADE_POST_RUN_LEARNING=1_to_ingest_candidate"}
        context = input_packet.context or {}
        domain = str(context.get("domain", "")).strip() or str(intent or "general")
        content = "\n".join(
            [
                f"run_id: {input_packet.run_id}",
                f"source: {input_packet.source}",
                f"intent: {intent}",
                f"input: {input_packet.user_input}",
                f"response: {output.response}",
                f"verification_status: {report.status}",
            ]
        )
        candidate = LearningPipeline(db_path=self.db_path).ingest(
            content=content,
            source_type="conversation",
            source_ref=f"run:{input_packet.run_id}",
            title=f"Post-run learning {input_packet.run_id}",
            domain=domain,
            risk_level="low",
        )
        return {
            "enabled": True,
            "mode": "candidate_only",
            "candidate_id": candidate.get("candidate_id"),
            "status": candidate.get("status"),
            "source_ref": candidate.get("source_ref"),
            "policy": "No se evalua, verifica ni consolida sin pasos explicitos posteriores.",
        }

    def _propose_neuron_candidate(self, input_packet: InputPacket, signals: Any) -> dict[str, Any]:
        """Propone (sin activar) una neurona candidata cuando la intención es de creación.

        Fase B · propuesta auditable: crea un NeuronSpec, lo evalúa como evidencia
        y lo registra SIEMPRE como `candidate`. La promoción a experimental/stable
        es una decisión humana posterior. Nunca degrada una neurona ya promovida.
        """
        from .neuron_creator import NeuronCreator
        from .neuron_registry import NeuronRegistry
        from .neuron_trainer import NeuronTrainer

        context = input_packet.context or {}
        name = (
            str(context.get("active_neuron", "")).strip()
            or str(context.get("project_id", "")).strip()
            or self._slug(input_packet.user_input)
        )
        domain = str(context.get("domain", "")).strip() or str(signals.intent) or "general"
        registry = NeuronRegistry(db_path=self.db_path)

        existing = registry.get_neuron(name)
        if existing and str(existing.get("status")) in {"experimental", "stable"}:
            return {
                "name": name,
                "source_run": input_packet.run_id,
                "registered_as": "skipped_existing_promoted",
                "existing_status": existing.get("status"),
                "activation": "requires_human_promotion",
                "note": "No se degrada una neurona ya promovida; propuesta omitida.",
            }

        spec = NeuronCreator().create(name=name, mission=input_packet.user_input, domain=domain)
        spec.status = "candidate"
        spec.created_by = "run_auto_proposal"
        assessment = NeuronTrainer().evaluate(spec)
        neuron_id = registry.register(spec)  # permanece como candidate; no se llama store_training (no promueve)
        return {
            "neuron_id": neuron_id,
            "name": spec.name,
            "domain": spec.domain,
            "registered_as": "candidate",
            "activation": "requires_human_promotion",
            "source_run": input_packet.run_id,
            "assessment": {
                "score": assessment.score,
                "assessed_status": assessment.status,
                "strengths": assessment.strengths,
                "warnings": assessment.warnings,
                "recommendations": assessment.recommendations,
            },
        }

    @staticmethod
    def _slug(text: str) -> str:
        cleaned = "".join(char.lower() if (char.isalnum() or char.isspace()) else " " for char in text)
        words = [word for word in cleaned.split() if len(word) >= 4][:3]
        return ("neurona-" + "-".join(words)) if words else "neurona-candidata"

    @staticmethod
    def _build_comparison_basis(input_packet: InputPacket, intent: str) -> dict[str, Any]:
        context = input_packet.context or {}
        session_id = str(context.get("session_id", "")).strip() or None
        project_id = str(context.get("project_id", "")).strip() or None
        active_neuron = str(context.get("active_neuron", "")).strip() or None
        explicit_scope = str(context.get("context_scope", "")).strip() or None
        if explicit_scope and explicit_scope not in {"source_intent", "session", "project", "neuron", "project_neuron"}: explicit_scope = None
        if explicit_scope == "project_neuron" and project_id and active_neuron: scope = "project_neuron"
        elif explicit_scope == "neuron" and active_neuron: scope = "neuron"
        elif explicit_scope == "project" and project_id: scope = "project"
        elif explicit_scope == "session" and session_id: scope = "session"
        elif project_id and active_neuron: scope = "project_neuron"
        elif active_neuron: scope = "neuron"
        elif project_id: scope = "project"
        elif session_id: scope = "session"
        else: scope = "source_intent"
        fields: list[tuple[str, str]] = [("intent", intent)]
        if scope == "project_neuron": fields.extend([("project_id", project_id or ""), ("active_neuron", active_neuron or "")])
        elif scope == "neuron": fields.append(("active_neuron", active_neuron or ""))
        elif scope == "project": fields.append(("project_id", project_id or ""))
        elif scope == "session": fields.append(("session_id", session_id or ""))
        else: fields.append(("source", input_packet.source))
        context_key = scope + "|" + "|".join(f"{key}={value}" for key, value in fields)
        return {
            "context_scope": scope,
            "context_key": context_key,
            "source": input_packet.source,
            "intent": intent,
            "session_id": session_id,
            "project_id": project_id,
            "active_neuron": active_neuron,
        }

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def recall(self, query: str, limit: int = 10) -> dict[str, Any]:
        episodes = self.bodega.list_recent_episodes(limit=limit)
        if query:
            query_lower = query.lower()
            episodes = [
                episode
                for episode in episodes
                if query_lower in (episode.get("title") or "").lower()
                or query_lower in (episode.get("summary") or "").lower()
                or query_lower in (episode.get("tags") or "").lower()
            ]
        return {"query": query, "count": len(episodes), "episodes": episodes}

    def doctor(self) -> dict[str, Any]:
        status = self.bodega.doctor(runs_dir=self.runs_dir)
        status["models"] = {
            "provider": self.model_provider,
            "hypothalamus": self.hypothalamus_model,
            "central": self.central_model,
            "selection": self.model_selection,
            "ollama": self.model_client.health() if self.model_client else {"ok": False, "disabled": True},
        }
        status["runtime"] = self._runtime_status()
        status["learning"] = {
            "post_run_learning_enabled": str(os.environ.get("TRIADE_POST_RUN_LEARNING", "")).strip().lower()
            in {"1", "true", "yes", "on"}
        }
        return status

    @staticmethod
    def _runtime_status() -> dict[str, Any]:
        virtual_env = os.environ.get("VIRTUAL_ENV")
        return {
            "python_version": platform.python_version(),
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "cwd": str(Path.cwd()),
            "stdout_encoding": getattr(sys.stdout, "encoding", None),
            "virtual_env": virtual_env,
            "in_virtual_env": bool(virtual_env) or sys.prefix != sys.base_prefix,
        }

    @staticmethod
    def _score_hypothalamus(signals: Any, model_result: dict[str, Any]) -> float:
        score = 0.55
        if model_result.get("ok"):
            score += 0.20
        if signals.intent in {"conversation", "build_or_update", "analyze", "memory"}:
            score += 0.10
        if signals.risk in {"low", "medium", "high", "critical"}:
            score += 0.05
        if isinstance(signals.pv7, dict) and len(signals.pv7) >= 7:
            score += 0.05
        if signals.notes:
            score += 0.05
        return round(min(score, 1.0), 3)

    @staticmethod
    def _score_central(response: str, model_ok: bool) -> float:
        score = 0.50 + (0.20 if model_ok else 0.0)
        if response and len(response.strip()) > 20:
            score += 0.10
        if any(marker in response.lower() for marker in ["verific", "traz", "memoria", "cristal", "riesgo"]):
            score += 0.10
        return round(min(score, 1.0), 3)

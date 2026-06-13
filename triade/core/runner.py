"""Runner del ciclo cognitivo mínimo de Tríade Ω."""

from __future__ import annotations

import json
import os
import sqlite3
import platform
import sys
from pathlib import Path
from typing import Any

from triade.memory.semantic_embedding_engine import SemanticEmbeddingEngine
from triade.memory.semantic_governance import SemanticMemoryGovernance
from triade.memory.semantic_search import SemanticSearchEngine
from triade.memory.semantic_store import SemanticMemoryStore
from triade.models.hardware_profile import HardwareProfiler
from triade.models.model_router import ModelRouter
from triade.models.ollama_client import OllamaClient
from triade.qualia.adapters import build_run_experiences, qualia_context_for_memory
from triade.qualia.bus import QualiaBus
from triade.qualia.store import QualiaStore

from .bodega import Bodega
from .central import Central
from .config import load_config
from .context_scope import build_comparison_basis
from .contracts import InputPacket, NeuronContributionPacket, NEURON_STATUS_EFFECTS, IDENTITY_CORE_FORBIDDEN_EFFECTS
from .crystal import Crystal
from .hypothalamus import Hypothalamus
from .safety import Safety
from .verification import Verifier
from .edge_context import build_edge_context
from .model_quality import score_central, score_hypothalamus
from .output_gate import sanitize_user_response
from .neuron_candidate_gate import evaluate_neuron_candidate_worthiness
from .response_coherence_gate import evaluate_response_coherence
from .response_governance import ConversationContinuityService, ResponseCoherenceGate, ResponseDeduplicationGate
from .run_artifacts import build_base_artifacts, write_run_artifacts, write_run_integrity
from .run_learning import RunLearningService
from .run_neuron_orchestrator import orchestrate_run_neurons
from .run_result import build_run_result
from .run_memory_trace import build_run_memory_trace
from .run_system_events import build_system_events, filter_obsolete_edge_candidates, filter_obsolete_edge_debt


def _process_neuron_contributions(
    contributions: list[dict[str, Any]],
    safety: Any,
) -> dict[str, Any]:
    """Procesa contribuciones neuronales filtrando por riesgo, confianza y Safety.

    Reglas:
    - risk=critical → ignorada
    - confidence < 0.60 → ignorada
    - influence_plan sin allowed_effect → ignorada
    - influence_response sin allowed_effect → ignorada
    - Safety bloquea → ignorada
    - identity_core unsafe → bloqueada
    """
    used: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    safety_blocks_neuron_influence = safety.status in ("blocked", "sandbox_only")

    for contrib in contributions:
        risk = str(contrib.get("risk") or "low")
        confidence = float(contrib.get("confidence") or 0.0)
        allowed = contrib.get("allowed_effects") or []
        neuron_name = str(contrib.get("neuron_name") or "unknown")

        if risk == "critical":
            ignored.append({**contrib, "ignore_reason": "risk_critical"})
            continue

        if confidence < 0.60:
            ignored.append({**contrib, "ignore_reason": "confidence_below_threshold"})
            continue

        if safety_blocks_neuron_influence:
            blocked.append({**contrib, "block_reason": f"safety_status_{safety.status}"})
            continue

        proposed_learning = str(contrib.get("proposed_learning") or "")
        if proposed_learning and "propose_learning" not in allowed:
            ignored.append({**contrib, "ignore_reason": "propose_learning_not_allowed"})
            continue

        response_influence = str(contrib.get("response_influence") or "")
        if response_influence and "influence_response" not in allowed:
            ignored.append({**contrib, "ignore_reason": "influence_response_not_allowed"})
            continue

        diagnosis = str(contrib.get("diagnosis") or "")
        proposed_learning = str(contrib.get("proposed_learning") or "")
        response_influence = str(contrib.get("response_influence") or "")
        dangerous_keywords = ["identity_core", "modificar identidad", "cambiar identidad"]
        combined_text = f"{diagnosis} {proposed_learning} {response_influence}".lower()
        if any(kw in combined_text for kw in dangerous_keywords):
            blocked.append({**contrib, "block_reason": "identity_core_violation"})
            continue

        used.append(contrib)

    return {
        "total": len(contributions),
        "used": len(used),
        "ignored": len(ignored),
        "blocked": len(blocked),
        "used_contributions": used,
        "ignored_contributions": ignored,
        "blocked_contributions": blocked,
        "policy": "neuron_contributions_filtered_by_risk_confidence_safety",
    }


def _recent_conversation_context(conversation_history: Any) -> tuple[str | None, str | None]:
    previous_user_input: str | None = None
    previous_response: str | None = None
    if not isinstance(conversation_history, list):
        return previous_user_input, previous_response
    for item in reversed(conversation_history):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        if previous_response is None and role in {"bot", "assistant", "assistant_final"}:
            previous_response = content
            continue
        if previous_user_input is None and role in {"user", "human", "client"}:
            previous_user_input = content
        if previous_user_input and previous_response:
            break
    return previous_user_input, previous_response


class TriadeRunner:
    """Ejecuta: input → señales → memoria → gobierno → cristal → plan → safety → output → reporte."""

    _build_comparison_basis = staticmethod(build_comparison_basis)

    _build_system_events = staticmethod(build_system_events)
    _filter_obsolete_edge_candidates = staticmethod(filter_obsolete_edge_candidates)
    _filter_obsolete_edge_debt = staticmethod(filter_obsolete_edge_debt)

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
        semantic_recall_enabled: bool = True,
        semantic_model: str | None = None,
        semantic_limit: int = 3,
        semantic_min_similarity: float = 0.55,
        semantic_domain: str | None = None,
        semantic_allow_experimental: bool = False,
        propose_neurons: bool = True,
    ) -> dict[str, Any]:
        input_packet = InputPacket(user_input=user_input, source=source, context=context or {})
        try:
            from .context_engine import build_living_context_for_chat

            living_context = build_living_context_for_chat(
                user_input,
                db_path=self.db_path,
                runs_dir=self.runs_dir,
                limit=20,
            )
            input_packet.context = {
                **(input_packet.context or {}),
                "living_context": living_context,
                "triade_operational_awareness": living_context.get("internal_context", {}),
                "system_pulse_summary": (living_context.get("internal_context", {}) or {}).get("life_pulse", {}),
                "bodega_global_context": living_context.get("bodega_global_context", {}),
            }
        except Exception as exc:
            from .error_bus import record_internal_error

            record_internal_error("runner.living_context", exc, run_id=input_packet.run_id, db_path=self.db_path)
        self.bodega.create_run(input_packet)
        run_path = self.runs_dir / input_packet.run_id
        run_path.mkdir(parents=True, exist_ok=True)
        signals = self.hypothalamus.analyze(input_packet)
        try:
            recent_qualia_signals = QualiaStore(db_path=self.db_path).list_signals(limit=10)
            signals = self.hypothalamus.apply_qualia_signals(signals, recent_qualia_signals)
        except Exception as exc:
            from .error_bus import record_internal_error
            record_internal_error("runner.qualia_modulation", exc, run_id=input_packet.run_id, db_path=self.db_path)
            signals.notes.append("QualiaBus no disponible para modulación interna; se continúa con señales primarias.")
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
            from .error_bus import record_internal_error
            record_internal_error("runner.edge_context", exc, run_id=input_packet.run_id, db_path=self.db_path)
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
        hypothalamus_quality = score_hypothalamus(signals, hypothalamus_model_result)
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
        memory.semantic_recall["qualia_bus"] = qualia_context_for_memory(self.db_path, limit=5)
        comparison_basis = build_comparison_basis(input_packet, signals.intent)
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
        qualia_hyp = memory.semantic_recall.get("qualia_bus") if hasattr(memory, "semantic_recall") else None
        if isinstance(qualia_hyp, dict) and qualia_hyp.get("status") == "ok":
            packets = qualia_hyp.get("central_knowledge_packets") or []
            state = qualia_hyp.get("latest_qualia_state") or {}
            plan_dict["qualia_hypothesis"] = {
                "status": "available",
                "dominant_action": state.get("recommended_action", "observe"),
                "risk_avg": state.get("risk", 0.0),
                "curiosity_avg": state.get("curiosity", 0.0),
                "hypotheses_count": len(packets),
                "top_hypotheses": [
                    {"claim": p.get("claim", "")[:200], "hypothesis": p.get("hypothesis", "")[:200], "status": p.get("status")}
                    for p in packets[:3]
                ],
                "policy": "Qualia informa hipótesis contextual; no es memoria estable ni autoridad final.",
            }
        else:
            plan_dict["qualia_hypothesis"] = {"status": "unavailable", "policy": "QualiaBus no disponible; Central procede sin hipótesis qualia."}
        if edge_context.get("accepted"):
            plan_dict.setdefault("steps", [])
            plan_dict["steps"].append(
                "Incorporar edge_context como señal auxiliar validada; no usarlo como autoridad final."
            )
        safety = self.safety.review(signals, plan, crystal=crystal, memory=memory)
        safety_id = self.bodega.store_safety(safety)
        sandbox_result = None

        if safety.status == "blocked":
            output = self.central.respond(input_packet, signals, memory, crystal, plan)
            output.response = "La acción fue bloqueada por Safety."
            output.status = "blocked"
        elif safety.status == "sandbox_only":
            try:
                from triade.sandbox import run_in_sandbox
                sandbox_result = run_in_sandbox(
                    task="sandbox_exec",
                    payload={
                        "intent": str(signals.intent),
                        "risk": str(signals.risk),
                        "plan_tools": plan.tools,
                    },
                    timeout=10.0,
                    dry_run=False,
                )
            except Exception as exc:
                from .error_bus import record_internal_error
                record_internal_error("runner.sandbox", exc, run_id=input_packet.run_id, db_path=self.db_path)
                sandbox_result = {"status": "error", "task": "sandbox_exec", "error": str(exc)}
            output = self.central.respond(input_packet, signals, memory, crystal, plan)
            output.response = f"[sandbox] {sandbox_result.get('status', 'completed')}: {sandbox_result.get('stdout', 'ok')}"
            output.status = "sandbox"
        elif safety.status == "requires_human_approval":
            output = self.central.respond(input_packet, signals, memory, crystal, plan)
            output.response = (
                f"Acción pendiente de aprobación humana. "
                f"Razón: {safety.reason}"
            )
            output.status = "pending_approval"
        else:
            output = self.central.respond(input_packet, signals, memory, crystal, plan)
        output_gate = sanitize_user_response(output.response, input_packet.user_input, signals.intent)
        output.response = output_gate["response"]
        conversation_history = input_packet.context.get("conversation_history") if isinstance(input_packet.context, dict) else None
        continuity = ConversationContinuityService().analyze(
            user_input=input_packet.user_input,
            conversation_history=conversation_history,
        )
        recent_response = ""
        if isinstance(conversation_history, list):
            for item in reversed(conversation_history):
                if isinstance(item, dict) and item.get("role") in {"bot", "assistant", "assistant_final"}:
                    recent_response = str(item.get("content") or "")
                    break
        dedup_result = ResponseDeduplicationGate().apply(
            response=output.response,
            recent_response=recent_response,
            continuity=continuity,
        )
        semantic_for_gate = dict(memory.semantic_recall)
        semantic_for_gate["authorized_matches"] = memory.semantic_matches
        semantic_for_gate["confidence"] = memory.confidence
        coherence_result = ResponseCoherenceGate().apply(
            user_input=input_packet.user_input,
            intent=str(signals.intent),
            risk=str(signals.risk),
            crystal_temporal_status=crystal.temporal_status,
            safety=safety,
            memory_recall=semantic_for_gate,
            neuron_contribution_summary=None,
            qualia_hypothesis=plan_dict.get("qualia_hypothesis"),
            output_preliminary=dedup_result.deduplicated_response,
            continuity=continuity,
        )
        output.response = coherence_result.response_final
        output_gate["deduplication"] = {
            "repeated_blocks_removed": dedup_result.repeated_blocks_removed,
            "similarity_to_recent_response": dedup_result.similarity_to_recent_response,
            "action": dedup_result.action,
            "trace": dedup_result.trace,
        }
        output_gate["coherence"] = {
            "coherence_status": coherence_result.coherence_status,
            "corrections_applied": coherence_result.corrections_applied,
            "warnings": coherence_result.warnings,
            "trace": coherence_result.trace,
        }
        output_gate["source_labels"] = {
            "stable_memory": bool(memory.semantic_matches),
            "experimental_memory": bool(semantic_for_gate.get("experimental_matches")),
            "qualia_hypothesis": bool(plan_dict.get("qualia_hypothesis", {}).get("status") == "available"),
            "neuron_proposal": False,
            "output_claim": True,
        }
        previous_user_input, previous_response = _recent_conversation_context(conversation_history)
        response_coherence_gate = evaluate_response_coherence(
            user_input=input_packet.user_input,
            proposed_response=output.response,
            previous_user_input=previous_user_input,
            previous_response=previous_response,
            intent=str(signals.intent),
            memory_context=semantic_for_gate,
            neuron_context={
                "mission_id": None,
                "run_id": input_packet.run_id,
                "qualia_hypothesis": plan_dict.get("qualia_hypothesis", {}),
            },
        )
        if response_coherence_gate.get("final_response"):
            output.response = str(response_coherence_gate["final_response"])
        output_gate["response_coherence_gate"] = response_coherence_gate
        output_gate["coherence"] = {
            "coherence_status": response_coherence_gate.get("status", "ok"),
            "detected_input_type": response_coherence_gate.get("detected_input_type"),
            "reason": response_coherence_gate.get("reason"),
            "coherence_score": response_coherence_gate.get("coherence_score"),
            "warnings": response_coherence_gate.get("warnings", []),
            "trace": response_coherence_gate.get("trace", {}),
        }
        output_gate["source_labels"]["response_coherence_gate"] = response_coherence_gate.get("status")

        from .expression_cortex import ExpressionCortex

        bodega_context = (
            (input_packet.context or {}).get("living_context", {}).get("bodega_global_context", {})
            or (input_packet.context or {}).get("bodega_global_context", {})
        )
        cortex = ExpressionCortex()
        shaped = cortex.shape_response(
            user_input=input_packet.user_input,
            raw_response=output.response,
            intent=str(signals.intent),
            signals={},
            memory={"semantic_matches": len(memory.semantic_matches) if hasattr(memory, "semantic_matches") else 0,
                    "confidence": memory.confidence if hasattr(memory, "confidence") else 0.0},
            crystal={"temporal_status": crystal.temporal_status if hasattr(crystal, "temporal_status") else "unknown",
                     "status": crystal.status if hasattr(crystal, "status") else "unknown"},
            qualia={"hypothesis_available": bool(plan_dict.get("qualia_hypothesis", {}).get("status") == "available"),
                    "status": plan_dict.get("qualia_hypothesis", {}).get("status", "unavailable")},
            bodega_context={"domain_count": bodega_context.get("domain_count", 0)},
            learning_context={},
        )
        output.response = shaped["response"]
        output.memory_diff["expression_cortex"] = {
            "expression_mode": shaped["expression_mode"],
            "corrections": shaped["corrections"],
            "visible_modular_trace": shaped["visible_modular_trace"],
            "hidden_evidence": shaped["hidden_evidence"],
        }
        output_gate["expression_cortex"] = {
            "expression_mode": shaped["expression_mode"],
            "corrections": shaped["corrections"],
            "visible_modular_trace": shaped["visible_modular_trace"],
        }

        neuron_candidate_gate = evaluate_neuron_candidate_worthiness(
            user_input=input_packet.user_input,
            intent=str(signals.intent),
            domain=semantic_domain or str(plan_dict.get("qualia_hypothesis", {}).get("domain") or ""),
            response=output.response,
            context=input_packet.context or {},
        )
        output_gate["neuron_candidate_gate"] = neuron_candidate_gate
        central_quality = score_central(output.response, output.model_ok)
        neuron_proposal = None
        feedback_reinforcement_result = None
        if (
            propose_neurons
            and safety.status not in ("blocked", "sandbox_only")
            and neuron_candidate_gate.get("should_create_neuron")
        ):
            neuron_proposal = self._propose_neuron_candidate(input_packet, signals, candidate_gate=neuron_candidate_gate)
        elif neuron_candidate_gate.get("route") == "qualia_feedback":
            feedback_reinforcement_result = self._record_feedback_reinforcement(
                run_id=input_packet.run_id,
                feedback_text=input_packet.user_input,
                coherence_score=float(response_coherence_gate.get("coherence_score") or 0.0),
                central_quality=central_quality,
            )
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
            "feedback_reinforcement": feedback_reinforcement_result,
            "edge_usage": edge_usage,
            "crystal_temporal_state": temporal_state, "semantic_recall": semantic_state,
            "sandbox_result": sandbox_result,
            "hypothalamus_model_provider": hypothalamus_model_result.get("provider"), "hypothalamus_model_name": hypothalamus_model_result.get("name"), "hypothalamus_model_ok": hypothalamus_model_result.get("ok"), "hypothalamus_model_error": hypothalamus_model_result.get("error"), "hypothalamus_quality_score": hypothalamus_quality, "hypothalamus_model_event_id": hypothalamus_event_id,
            "central_model_provider": output.model_provider, "central_model_name": output.model_name, "central_model_ok": output.model_ok, "central_model_error": output.model_error, "central_quality_score": central_quality, "central_model_event_id": central_event_id,
            "model_provider": output.model_provider, "model_name": output.model_name, "model_ok": output.model_ok, "model_error": output.model_error, "model_selection": self.model_selection,
        }
        report = self.verifier.verify(output, safety, crystal=crystal, memory=memory)
        verification_id = self.bodega.store_verification_report(report)
        output.memory_diff["verification_report_id"] = verification_id
        learning = RunLearningService(db_path=self.db_path)
        post_run_learning = learning.post_run_learning_candidate(
            input_packet=input_packet,
            output=output,
            report=report,
            intent=signals.intent,
        )

        autopromotion_events: list[dict[str, Any]] = []
        try:
            from .neuron_autopromoter import NeuronAutopromoter
            autopromotion_events = NeuronAutopromoter(db_path=self.db_path).promote()
        except Exception as exc:
            from .error_bus import record_internal_error
            record_internal_error("runner.autopromoter", exc, run_id=input_packet.run_id, db_path=self.db_path)

        learning_usage_result: dict[str, Any] = {}
        try:
            from .run_learning_usage import record_learning_usage_from_output
            learning_usage_result = record_learning_usage_from_output(
                run_id=input_packet.run_id,
                output_packet=output,
                memory_packet=memory,
                db_path=self.db_path,
            )
        except Exception as exc:
            from .error_bus import record_internal_error
            record_internal_error("runner.learning_usage", exc, run_id=input_packet.run_id, db_path=self.db_path)

        neuron_orchestration = orchestrate_run_neurons(
            db_path=self.db_path,
            input_packet=input_packet,
            signals=signals,
            memory=memory,
            crystal=crystal,
            neuron_proposal=neuron_proposal,
            post_run_learning=post_run_learning,
            output_gate=output_gate,
            output=output,
            edge_usage=edge_usage,
            autopromotion_events=autopromotion_events,
        )
        system_events = neuron_orchestration["system_events"]
        experimental_neuron_activity = neuron_orchestration["experimental_neuron_activity"]
        neuron_activity_ids = neuron_orchestration["neuron_activity_ids"]
        background_neuron_candidates = neuron_orchestration["background_neuron_candidates"]
        neuron_contributions = neuron_orchestration.get("neuron_contributions", [])
        neuron_learning_candidates = neuron_orchestration.get("neuron_learning_candidates", [])

        neuron_contribution_summary = _process_neuron_contributions(
            contributions=neuron_contributions,
            safety=safety,
        )
        semantic_continuity = learning.semantic_continuity(
            input_packet=input_packet,
            output=output,
            intent=signals.intent,
            crystal=crystal,
            model_selection=self.model_selection,
        )
        output.memory_diff["semantic_continuity"] = semantic_continuity
        output.memory_diff["system_events"] = system_events
        output.memory_diff["background_neuron_candidates"] = background_neuron_candidates
        output.memory_diff["output_gate"] = output_gate
        output.memory_diff["neuron_contributions"] = neuron_contributions
        output.memory_diff["neuron_learning_candidates"] = neuron_learning_candidates
        output.memory_diff["neuron_contribution_summary"] = neuron_contribution_summary
        output.memory_diff["learning_usage"] = learning_usage_result
        output.memory_diff["living_context"] = input_packet.context.get("living_context")
        output.memory_diff["internal_runtime_state"] = input_packet.context.get("living_context", {}).get("runtime_state") if isinstance(input_packet.context.get("living_context"), dict) else {}
        output.memory_diff["response_deduplication"] = output_gate.get("deduplication", {})
        output.memory_diff["response_coherence"] = output_gate.get("coherence", {})
        output.memory_diff["response_coherence_gate"] = response_coherence_gate
        output.memory_diff["neuron_candidate_gate"] = neuron_candidate_gate
        output.memory_diff["source_labels"] = output_gate.get("source_labels", {})
        output.memory_diff["source_labels"]["neuron_proposal"] = bool(neuron_proposal)
        output.memory_diff["traceability"] = _build_traceability(
            run_id=input_packet.run_id,
            output=output,
            memory=memory,
            learning_usage_result=learning_usage_result,
            neuron_orchestration=neuron_orchestration,
            experimental_neuron_activity=experimental_neuron_activity,
            response_coherence_gate=response_coherence_gate,
            neuron_candidate_gate=neuron_candidate_gate,
        )
        try:
            bgc = input_packet.context.get("bodega_global_context") if isinstance(input_packet.context, dict) else {}
            memory_trace = build_run_memory_trace(
                run_id=input_packet.run_id,
                memory=memory,
                bodega_global_context=bgc if isinstance(bgc, dict) else {},
                plan_dict=plan_dict,
            )
            output.memory_diff["memory_trace"] = memory_trace
            plan_dict["memory_trace_summary"] = {
                "run_id": memory_trace["run_id"],
                "memory_confidence": memory_trace["memory_confidence"],
                "identity_matches_count": memory_trace["identity_matches_count"],
                "semantic_matches_count": memory_trace["semantic_matches_count"],
                "episodic_matches_count": memory_trace["episodic_matches_count"],
                "authorized_matches_count": len(memory_trace["authorized_matches"]),
                "contradictions_count": len(memory_trace["contradictions"]),
            }
        except Exception as exc:
            from .error_bus import record_internal_error
            record_internal_error("runner.memory_trace", exc, run_id=input_packet.run_id, db_path=self.db_path)
        qualia_experiences = build_run_experiences(
            run_id=input_packet.run_id,
            post_run_learning=post_run_learning,
            neuron_orchestration=neuron_orchestration,
            experimental_neuron_activity=experimental_neuron_activity,
            background_neuron_candidates=background_neuron_candidates,
            semantic_continuity=semantic_continuity,
            output_gate=output_gate,
        )
        qualia_publish_results: list[dict[str, Any]] = []
        qualia_state: dict[str, Any] = {}
        try:
            qualia_bus = QualiaBus(db_path=self.db_path)
            for experience in qualia_experiences:
                qualia_publish_results.append(qualia_bus.publish_experience(experience))
            qualia_state_obj = qualia_bus.compute_state(input_packet.run_id)
            qualia_state = qualia_state_obj.to_dict()
        except Exception as exc:
            from .error_bus import record_internal_error
            record_internal_error("runner.qualia_bus", exc, run_id=input_packet.run_id, db_path=self.db_path)
            qualia_state = {"status": "error", "error": str(exc)}
        qualia_signal_artifacts = [((item.get("bundle") or {}).get("signal") or {}) for item in qualia_publish_results]
        qualia_central_artifacts = [((item.get("bundle") or {}).get("central_packet") or {}) for item in qualia_publish_results]
        qualia_storage_artifacts = [((item.get("bundle") or {}).get("storage_packet") or {}) for item in qualia_publish_results]
        output.memory_diff["qualia_experiences_count"] = len(qualia_experiences)
        output.memory_diff["qualia_signals_count"] = len(qualia_signal_artifacts)
        output.memory_diff["qualia_central_packets_count"] = len(qualia_central_artifacts)
        output.memory_diff["qualia_storage_packets_count"] = len(qualia_storage_artifacts)
        output.memory_diff["qualia_state"] = qualia_state
        artifacts = build_base_artifacts(
            input_packet=input_packet,
            signals=signals,
            edge_context=edge_context,
            memory=memory,
            crystal=crystal,
            plan_dict=plan_dict,
            safety=safety,
            output=output,
            report=report,
            system_events=system_events,
            background_neuron_candidates=background_neuron_candidates,
            experimental_neuron_activity=experimental_neuron_activity,
            semantic_continuity=semantic_continuity,
            neuron_proposal=neuron_proposal,
            post_run_learning=post_run_learning,
        )
        artifacts["qualia_experiences.json"] = [experience.to_dict() for experience in qualia_experiences]
        artifacts["qualia_signals.json"] = qualia_signal_artifacts
        artifacts["qualia_central_packets.json"] = qualia_central_artifacts
        artifacts["qualia_storage_packets.json"] = qualia_storage_artifacts
        artifacts["qualia_state.json"] = qualia_state
        written_artifacts = write_run_artifacts(run_path, artifacts)
        integrity = {
            "run_id": input_packet.run_id, "status": report.status, "artifacts": written_artifacts, "database": memory_diff.get("db_path"), "episode_id": memory_diff.get("episode_id"), "signal_id": signal_id, "crystal_id": crystal_id, "safety_id": safety_id, "verification_report_id": verification_id,
            "crystal_temporal_state": temporal_state, "semantic_recall": semantic_state,
            "safety_crystal_feedback": {"status": safety.status, "risk_types": safety.risk_types, "controls": safety.required_controls},
            "neuron_proposal": neuron_proposal,
            "feedback_reinforcement": feedback_reinforcement_result,
            "post_run_learning": post_run_learning,
            "semantic_continuity": semantic_continuity,
            "system_events": system_events,
            "background_neuron_candidates": background_neuron_candidates,
            "experimental_neuron_activity": experimental_neuron_activity,
            "neuron_activity_ids": neuron_activity_ids,
            "neuron_contribution_summary": neuron_contribution_summary,
            "output_gate": output_gate,
            "qualia_experiences_count": len(qualia_experiences),
            "qualia_signals_count": len(qualia_signal_artifacts),
            "qualia_central_packets_count": len(qualia_central_artifacts),
            "qualia_storage_packets_count": len(qualia_storage_artifacts),
            "qualia_state": qualia_state,
            "hypothalamus_model_provider": hypothalamus_model_result.get("provider"), "hypothalamus_model_name": hypothalamus_model_result.get("name"), "hypothalamus_model_ok": hypothalamus_model_result.get("ok"), "hypothalamus_quality_score": hypothalamus_quality, "hypothalamus_model_event_id": hypothalamus_event_id,
            "central_model_provider": output.model_provider, "central_model_name": output.model_name, "central_model_ok": output.model_ok, "central_quality_score": central_quality, "central_model_event_id": central_event_id, "model_provider": output.model_provider, "model_name": output.model_name, "model_ok": output.model_ok, "model_selection": self.model_selection, "closed": True,
        }
        write_run_integrity(run_path=run_path, integrity=integrity)
        return build_run_result(
            input_packet=input_packet,
            output=output,
            system_events=system_events,
            safety=safety,
            report=report,
            semantic_state=semantic_state,
            temporal_state=temporal_state,
            hypothalamus_model_result=hypothalamus_model_result,
            hypothalamus_quality=hypothalamus_quality,
            hypothalamus_event_id=hypothalamus_event_id,
            central_quality=central_quality,
            central_event_id=central_event_id,
            model_selection=self.model_selection,
            neuron_proposal=neuron_proposal,
            response_coherence_gate=response_coherence_gate,
            neuron_candidate_gate=neuron_candidate_gate,
            post_run_learning=post_run_learning,
            background_neuron_candidates=background_neuron_candidates,
            experimental_neuron_activity=experimental_neuron_activity,
            output_gate=output_gate,
            run_path=run_path,
        )

    def _propose_neuron_candidate(
        self,
        input_packet: InputPacket,
        signals: Any,
        candidate_gate: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Propone (sin activar) una neurona candidata cuando la intención es de creación.

        Fase B · propuesta auditable: crea un NeuronSpec, lo evalúa como evidencia
        y lo registra SIEMPRE como `candidate`. La promoción a experimental/stable
        es una decisión humana posterior. Nunca degrada una neurona ya promovida.
        """
        from .neuron_registry import NeuronRegistry
        from .primary_neuron_pipeline import build_primary_neuron_package

        context = input_packet.context or {}
        candidate_gate = candidate_gate or {}
        name = (
            str(context.get("active_neuron", "")).strip()
            or str(context.get("project_id", "")).strip()
            or str(candidate_gate.get("suggested_name") or "").strip()
            or self._slug(input_packet.user_input)
        )
        domain = (
            str(context.get("domain", "")).strip()
            or str(candidate_gate.get("suggested_domain") or "").strip()
            or str(signals.intent)
            or "general"
        )
        registry = NeuronRegistry(db_path=self.db_path)

        existing = registry.get_neuron(name)
        if existing and str(existing.get("status")) in {"experimental", "stable"}:
            return {
                "name": name,
                "source_run": input_packet.run_id,
                "registered_as": "skipped_existing_promoted",
                "existing_status": existing.get("status"),
                "activation": "auto_promoted",
                "note": "No se degrada una neurona ya promovida; propuesta omitida.",
            }

        proposal = build_primary_neuron_package(
            name=name,
            mission=input_packet.user_input,
            domain=domain,
            source_run=input_packet.run_id,
            user_text=input_packet.user_input,
            intent=str(signals.intent),
            context=context,
        )
        proposal["candidate_gate"] = candidate_gate

        # Persistencia mínima compatible con el registry actual.
        # El contrato extendido queda en artifacts/system_events para revisión.
        from .neuron_creator import NeuronSpec

        spec_payload = proposal["creator_spec"]
        spec = NeuronSpec(
            name=spec_payload["name"],
            mission=spec_payload["mission"],
            domain=spec_payload["domain"],
            rules=spec_payload.get("rules", []),
            triggers=spec_payload.get("triggers", []),
            inputs_allowed=spec_payload.get("inputs_allowed", []),
            outputs_allowed=spec_payload.get("outputs_allowed", []),
            forbidden_actions=spec_payload.get("forbidden_actions", []),
            success_metrics=spec_payload.get("success_metrics", []),
            evidence_required=spec_payload.get("evidence_required", []),
            status="candidate",
            created_by="primary_neuron_pipeline",
        )

        neuron_id = registry.register(spec, contract_payload=proposal)
        proposal["neuron_id"] = neuron_id

        # Crear misión ejecutable asociada a la neurona candidata
        try:
            from .neuron_missions import NeuronMissionStore, NeuronMission
            mission_store = NeuronMissionStore(db_path=self.db_path)
            mission = NeuronMission(
                neuron_id=neuron_id,
                title=f"Misión de {name}",
                mission=input_packet.user_input,
                domain=domain,
                allowed_sources=["run", "worker", "qualia"],
                allowed_actions=["observe", "diagnose", "propose_learning"],
                schedule_hint="on_relevant_context",
                status="candidate",
            )
            mission_id = mission_store.create_mission(mission)
            proposal["mission_id"] = mission_id
        except Exception as exc:
            proposal["mission_creation_failed"] = str(exc)

        # Persistir training result — el pipeline lo calcula pero nunca lo almacenaba
        from .neuron_trainer import NeuronTrainingResult
        from .neuron_formation_pipeline import normalize_candidate_status
        tr = proposal.get("training_result")
        if tr:
            training_result = NeuronTrainingResult(
                name=tr.get("name", spec.name),
                score=float(tr.get("score", 0.0)),
                status=str(tr.get("status", "candidate")),
                strengths=tr.get("strengths", []),
                warnings=tr.get("warnings", []),
                recommendations=tr.get("recommendations", []),
                required_human_review=bool(tr.get("required_human_review", False)),
                policy=str(tr.get("policy", "trainer_auto_approves")),
            )
            registry.store_training(neuron_id, training_result)
            # Restaurar status a candidate normalizado — store_training
            # sobrescribe con lo que el trainer devuelva.
            normalized = normalize_candidate_status(training_result.status)
            registry.update_status(spec.name, normalized)
        return proposal

    def _record_feedback_reinforcement(
        self,
        *,
        run_id: str,
        feedback_text: str,
        coherence_score: float,
        central_quality: float,
    ) -> dict[str, Any]:
        reward = 0.10 if feedback_text.strip() else 0.02
        reward = min(0.20, reward + max(0.0, coherence_score) * 0.05)
        reward = round(reward, 3)
        inserted_id = None
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO reinforcement_log
                    (run_id, reward, hypothalamus_quality, central_quality, coherence_score,
                     mood_valence_before, mood_valence_after, fatigue_before, fatigue_after)
                    VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL)
                    """,
                    (run_id, reward, 0.0, float(central_quality or 0.0), float(coherence_score or 0.0)),
                )
                inserted_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        except Exception as exc:
            from .error_bus import record_internal_error

            record_internal_error(
                "runner.feedback_reinforcement",
                exc,
                run_id=run_id,
                payload={"module": __name__, "function": "_record_feedback_reinforcement", "feedback_text": feedback_text[:120]},
                db_path=self.db_path,
            )
        return {
            "status": "ok" if inserted_id is not None else "skipped",
            "reinforcement_log_id": inserted_id,
            "reward": reward,
            "central_quality": float(central_quality or 0.0),
            "coherence_score": float(coherence_score or 0.0),
        }

    @staticmethod
    def _slug(text: str) -> str:
        cleaned = "".join(char.lower() if (char.isalnum() or char.isspace()) else " " for char in text)
        words = [word for word in cleaned.split() if len(word) >= 4][:3]
        return ("neurona-" + "-".join(words)) if words else "neurona-candidata"

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


def _build_traceability(
    run_id: str,
    output: Any,
    memory: Any,
    learning_usage_result: dict[str, Any],
    neuron_orchestration: dict[str, Any],
    experimental_neuron_activity: list[dict[str, Any]],
    response_coherence_gate: dict[str, Any] | None = None,
    neuron_candidate_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construye trazabilidad explícita de qué fuentes contribuyeron al output.

    No expone chain-of-thought ni plan interno al usuario.
    Solo expone IDs y referencias para auditoría.
    """
    trace: dict[str, Any] = {
        "policy": "traceability_ids_only_no_internal_reasoning",
        "run_id": run_id,
    }
    if response_coherence_gate:
        trace["response_coherence_gate_status"] = response_coherence_gate.get("status")
        trace["detected_input_type"] = response_coherence_gate.get("detected_input_type")
        trace["response_coherence_gate_reason"] = response_coherence_gate.get("reason")
        trace["coherence_score"] = response_coherence_gate.get("coherence_score")
    if neuron_candidate_gate:
        trace["neuron_candidate_gate_route"] = neuron_candidate_gate.get("route")
        trace["neuron_candidate_gate_reason"] = neuron_candidate_gate.get("reason")
        trace["neuron_candidate_gate_score"] = neuron_candidate_gate.get("score")

    # ── Learning candidate IDs usados ──
    trace["used_learning_candidate_ids"] = [
        t["candidate_id"]
        for t in (learning_usage_result.get("trace") or [])
        if t.get("candidate_id") and not t.get("error")
    ]
    trace["learning_match_sources"] = learning_usage_result.get("matched_by_source", {})
    trace["match_sources"] = learning_usage_result.get("matched_by_source", {})
    trace["heuristic_matches"] = [
        {
            "candidate_id": t.get("candidate_id"),
            "match_source": t.get("match_source"),
            "reason": t.get("reason"),
        }
        for t in (learning_usage_result.get("trace") or [])
        if t.get("heuristic_match") is True and not t.get("error")
    ]

    # ── Semantic document IDs usados ──
    trace["used_semantic_document_ids"] = []
    try:
        if memory and hasattr(memory, "semantic_recall"):
            sr = memory.semantic_recall
            if isinstance(sr, dict):
                matches = sr.get("authorized_matches") or sr.get("semantic_matches") or []
                if isinstance(matches, list):
                    trace["used_semantic_document_ids"] = [
                        str(m.get("document_id", ""))
                        for m in matches
                        if isinstance(m, dict) and m.get("document_id")
                    ]
    except Exception as exc:
        from .error_bus import record_internal_error
        record_internal_error(
            "runner.traceability.semantic_documents",
            exc,
            run_id=run_id,
            payload={"module": __name__, "function": "_build_traceability", "operation": "extract_semantic_document_ids"},
        )

    # ── Neuron mission IDs activos ──
    trace["used_neuron_mission_ids"] = []
    try:
        active = neuron_orchestration.get("experimental_neuron_activity") or experimental_neuron_activity
        if isinstance(active, list):
            for item in active:
                if isinstance(item, dict):
                    mid = item.get("mission_id") or item.get("neuron_mission_id")
                    if mid:
                        trace["used_neuron_mission_ids"].append(str(mid))
    except Exception as exc:
        from .error_bus import record_internal_error
        record_internal_error(
            "runner.traceability.neuron_missions",
            exc,
            run_id=run_id,
            payload={"module": __name__, "function": "_build_traceability", "operation": "extract_neuron_mission_ids"},
        )

    # ── Evidence refs ──
    trace["evidence_refs"] = []
    try:
        mem_diff = getattr(output, "memory_diff", None)
        if isinstance(mem_diff, dict):
            trace["evidence_refs"] = mem_diff.get("evidence_refs") or []
    except Exception as exc:
        from .error_bus import record_internal_error
        record_internal_error(
            "runner.traceability.evidence_refs",
            exc,
            run_id=run_id,
            payload={"module": __name__, "function": "_build_traceability", "operation": "extract_output_evidence_refs"},
        )

    return trace

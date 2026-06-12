"""Runner del ciclo cognitivo mínimo de Tríade Ω."""

from __future__ import annotations

import json
import os
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
from .run_artifacts import build_base_artifacts, write_run_artifacts, write_run_integrity
from .run_learning import RunLearningService
from .run_neuron_orchestrator import orchestrate_run_neurons
from .run_result import build_run_result
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
            recent_qualia_signals = QualiaStore(db_path=self.db_path).list_signals(limit=10)
            signals = self.hypothalamus.apply_qualia_signals(signals, recent_qualia_signals)
        except Exception:
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

        if safety.status == "blocked":
            output = self.central.respond(input_packet, signals, memory, crystal, plan)
            output.response = "La acción fue bloqueada por Safety."
            output.status = "blocked"
        elif safety.status == "sandbox_only":
            from triade.sandbox import run_in_sandbox
            sb = run_in_sandbox(task="sandbox_exec", payload={
                "intent": str(signals.intent),
                "risk": str(signals.risk),
                "plan_tools": plan.tools,
            })
            output = self.central.respond(input_packet, signals, memory, crystal, plan)
            output.response = f"[sandbox] {sb.get('status', 'completed')}: {sb.get('stdout', 'ok')}"
            output.status = "sandbox"
        else:
            output = self.central.respond(input_packet, signals, memory, crystal, plan)
        output_gate = sanitize_user_response(output.response, input_packet.user_input, signals.intent)
        output.response = output_gate["response"]
        central_quality = score_central(output.response, output.model_ok)
        neuron_proposal = None
        if propose_neurons and safety.status not in ("blocked", "sandbox_only"):
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
        except Exception:
            pass

        learning_usage_result: dict[str, Any] = {}
        try:
            from .run_learning_usage import record_learning_usage_from_output
            learning_usage_result = record_learning_usage_from_output(
                run_id=input_packet.run_id,
                output_packet=output,
                memory_packet=memory,
                db_path=self.db_path,
            )
        except Exception:
            pass

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
            post_run_learning=post_run_learning,
            background_neuron_candidates=background_neuron_candidates,
            experimental_neuron_activity=experimental_neuron_activity,
            output_gate=output_gate,
            run_path=run_path,
        )

    def _propose_neuron_candidate(self, input_packet: InputPacket, signals: Any) -> dict[str, Any]:
        """Propone (sin activar) una neurona candidata cuando la intención es de creación.

        Fase B · propuesta auditable: crea un NeuronSpec, lo evalúa como evidencia
        y lo registra SIEMPRE como `candidate`. La promoción a experimental/stable
        es una decisión humana posterior. Nunca degrada una neurona ya promovida.
        """
        from .neuron_registry import NeuronRegistry
        from .primary_neuron_pipeline import build_primary_neuron_package

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

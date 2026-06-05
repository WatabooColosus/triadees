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

from .bodega import Bodega
from .central import Central
from .config import load_config
from .contracts import InputPacket
from .crystal import Crystal
from .hypothalamus import Hypothalamus
from .safety import Safety
from .verification import Verifier


class TriadeRunner:
    """Ejecuta: input → señales → memoria → gobierno → cristal → plan → safety → output → reporte."""

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
        safety = self.safety.review(signals, plan, crystal=crystal, memory=memory)
        safety_id = self.bodega.store_safety(safety)
        if safety.status == "blocked":
            output = self.central.respond(input_packet, signals, memory, crystal, plan)
            output.response = "La acción fue bloqueada por Safety."
            output.status = "blocked"
        else:
            output = self.central.respond(input_packet, signals, memory, crystal, plan)
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
        output.memory_diff = {
            **memory_diff, "signal_id": signal_id, "crystal_id": crystal_id, "safety_id": safety_id,
            "neuron_proposal": neuron_proposal,
            "crystal_temporal_state": temporal_state, "semantic_recall": semantic_state,
            "hypothalamus_model_provider": hypothalamus_model_result.get("provider"), "hypothalamus_model_name": hypothalamus_model_result.get("name"), "hypothalamus_model_ok": hypothalamus_model_result.get("ok"), "hypothalamus_model_error": hypothalamus_model_result.get("error"), "hypothalamus_quality_score": hypothalamus_quality, "hypothalamus_model_event_id": hypothalamus_event_id,
            "central_model_provider": output.model_provider, "central_model_name": output.model_name, "central_model_ok": output.model_ok, "central_model_error": output.model_error, "central_quality_score": central_quality, "central_model_event_id": central_event_id,
            "model_provider": output.model_provider, "model_name": output.model_name, "model_ok": output.model_ok, "model_error": output.model_error, "model_selection": self.model_selection,
        }
        report = self.verifier.verify(output, safety, crystal=crystal, memory=memory)
        verification_id = self.bodega.store_verification_report(report)
        output.memory_diff["verification_report_id"] = verification_id
        post_run_learning = self._post_run_learning_candidate(input_packet, output, report, signals.intent)
        output.memory_diff["post_run_learning"] = post_run_learning
        semantic_continuity = self._semantic_continuity(input_packet, output, signals.intent, crystal)
        output.memory_diff["semantic_continuity"] = semantic_continuity
        artifacts = {"input.json": input_packet.to_dict(), "signals.json": signals.to_dict(), "memory.json": memory.to_dict(), "crystal.json": crystal.to_dict(), "plan.json": plan.to_dict(), "safety.json": safety.to_dict(), "output.json": output.to_dict(), "memory_diff.json": output.memory_diff, "report.json": report.to_dict()}
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
            "hypothalamus_model_provider": hypothalamus_model_result.get("provider"), "hypothalamus_model_name": hypothalamus_model_result.get("name"), "hypothalamus_model_ok": hypothalamus_model_result.get("ok"), "hypothalamus_quality_score": hypothalamus_quality, "hypothalamus_model_event_id": hypothalamus_event_id,
            "central_model_provider": output.model_provider, "central_model_name": output.model_name, "central_model_ok": output.model_ok, "central_quality_score": central_quality, "central_model_event_id": central_event_id, "model_provider": output.model_provider, "model_name": output.model_name, "model_ok": output.model_ok, "model_selection": self.model_selection, "closed": True,
        }
        self._write_json(run_path / "integrity.json", integrity)
        (run_path / "CLOSED").write_text("closed\n", encoding="utf-8")
        return {"run_id": input_packet.run_id, "response": output.response, "safety": safety.to_dict(), "report": report.to_dict(), "memory_diff": output.memory_diff, "semantic_recall": semantic_state, "crystal_temporal_state": temporal_state, "models": {"hypothalamus": {**hypothalamus_model_result, "quality_score": hypothalamus_quality, "event_id": hypothalamus_event_id}, "central": {"provider": output.model_provider, "name": output.model_name, "ok": output.model_ok, "error": output.model_error, "quality_score": central_quality, "event_id": central_event_id}}, "model": {"provider": output.model_provider, "name": output.model_name, "ok": output.model_ok, "error": output.model_error}, "model_selection": self.model_selection, "neuron_proposal": neuron_proposal, "run_path": str(run_path)}

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
        return {"context_scope": scope, "context_key": context_key, "source": input_packet.source, "intent": intent, "session_id": session_id, "project_id": project_id, "active_neuron": active_neuron}

    def recall(self, query: str, limit: int = 10) -> dict[str, Any]:
        episodes = self.bodega.list_recent_episodes(limit=limit)
        if query: episodes = [ep for ep in episodes if query.lower() in (ep.get("title") or "").lower() or query.lower() in (ep.get("summary") or "").lower() or query.lower() in (ep.get("tags") or "").lower()]
        return {"query": query, "count": len(episodes), "episodes": episodes}

    def doctor(self) -> dict[str, Any]:
        status = self.bodega.doctor(runs_dir=self.runs_dir)
        status["models"] = {"provider": self.model_provider, "hypothalamus": self.hypothalamus_model, "central": self.central_model, "selection": self.model_selection, "ollama": self.model_client.health() if self.model_client else {"ok": False, "disabled": True}}
        status["runtime"] = self._runtime_status()
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
        score = 0.35
        if model_result.get("ok"): score += 0.25
        if signals.intent in {"conversation", "build_or_update", "analyze", "memory"}: score += 0.10
        if signals.urgency in {"low", "medium", "high"}: score += 0.10
        if signals.risk in {"low", "medium", "high", "critical"}: score += 0.10
        if len(signals.pv7) >= 7: score += 0.10
        return round(min(score, 1.0), 2)

    @staticmethod
    def _score_central(response: str, model_ok: bool) -> float:
        text = response.strip(); score = 0.35
        if model_ok: score += 0.25
        if len(text) >= 40: score += 0.15
        if len(text) <= 1800: score += 0.10
        if "Tríade" in text or "Triade" in text: score += 0.05
        if text.endswith((".", "!", "?")): score += 0.10
        return round(min(score, 1.0), 2)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

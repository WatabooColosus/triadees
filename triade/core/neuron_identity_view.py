"""Vista de identidad diferenciada para neuronas internas."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import NEURON_STATUS_EFFECTS
from .experimental_neuron_evidence import build_experimental_evidence_ledger
from .neuron_activity_store import NeuronActivityStore
from .neuron_registry import NeuronRegistry
from .stable_promotion_readiness import evaluate_stable_readiness
from triade.qualia.store import QualiaStore


INSUFFICIENT_IDENTITY_MESSAGE = (
    "Esta neurona aún no tiene evidencia suficiente para identificarse plenamente."
)


class NeuronIdentityView:
    """Serializer read-only que explica quién es cada neurona y qué evidencia tiene."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db", runs_dir: str | Path = "runs") -> None:
        self.db_path = Path(db_path)
        self.runs_dir = Path(runs_dir)

    def list(self, limit: int = 100) -> dict[str, Any]:
        registry = NeuronRegistry(db_path=self.db_path)
        neurons = registry.list_neurons(limit=limit)
        context = self._context(limit=limit)
        identities = [self._build_identity(registry, neuron, context, limit=limit) for neuron in neurons]
        counts: dict[str, int] = {}
        for item in identities:
            status = str(item.get("state") or "unknown")
            counts[status] = counts.get(status, 0) + 1
        return {
            "status": "ok",
            "mode": "neuron_identity_view",
            "summary": {"total_neurons": len(identities), "by_status": counts},
            "neurons": identities,
            "policy": {
                "identity_core_protected": True,
                "stable_requires_evidence": True,
                "candidate_is_limited": True,
                "experimental_is_hypothesis": True,
            },
        }

    def detail(self, name: str, limit: int = 20) -> dict[str, Any] | None:
        registry = NeuronRegistry(db_path=self.db_path)
        neuron = registry.get_neuron(name)
        if neuron is None:
            return None
        context = self._context(limit=limit)
        return {
            "status": "ok",
            "mode": "neuron_identity_detail",
            "neuron": self._build_identity(registry, neuron, context, limit=limit),
        }

    def _context(self, limit: int) -> dict[str, Any]:
        evidence = build_experimental_evidence_ledger(
            runs_dir=self.runs_dir,
            db_path=self.db_path,
            limit=limit,
            prefer_db=True,
        )
        readiness = evaluate_stable_readiness(runs_dir=self.runs_dir, limit=limit)
        activity = NeuronActivityStore(db_path=self.db_path).list_activity(limit=limit)
        qualia_experiences: list[dict[str, Any]] = []
        try:
            qualia_experiences = QualiaStore(db_path=self.db_path).list_experiences(limit=limit)
        except Exception:
            qualia_experiences = []
        return {
            "evidence_by_name": {
                str(item.get("name")): item
                for item in evidence.get("neurons") or []
                if item.get("name")
            },
            "readiness_by_name": {
                str(item.get("name")): item
                for item in readiness.get("neurons") or []
                if item.get("name")
            },
            "activity": activity,
            "qualia_experiences": qualia_experiences,
        }

    def _build_identity(
        self,
        registry: NeuronRegistry,
        neuron: dict[str, Any],
        context: dict[str, Any],
        limit: int,
    ) -> dict[str, Any]:
        name = str(neuron.get("name") or "")
        status = str(neuron.get("status") or "candidate")
        domain = str(neuron.get("domain") or "unknown")
        evidence = context["evidence_by_name"].get(name, {})
        readiness = context["readiness_by_name"].get(name, {})
        activity = [
            item for item in context["activity"]
            if str(item.get("name") or "") == name or str(item.get("neuron_id") or "") == str(neuron.get("id") or "")
        ][:5]
        qualia = [
            item for item in context["qualia_experiences"]
            if str(item.get("neuron_id") or "") in {str(neuron.get("id") or ""), name}
        ][:5]
        training = registry.list_training(int(neuron["id"]), limit=limit) if neuron.get("id") else []
        latest_training = training[0] if training else {}
        score = float(latest_training.get("score") or 0.0)
        activation_count = int(evidence.get("activation_count") or 0)
        has_evidence = bool(training or activity or activation_count or qualia)
        ready_for_stable = bool(readiness.get("ready_for_stable_review"))
        promotion_reason = self._promotion_reason(status, ready_for_stable, evidence, latest_training)

        if status == "stable" and not has_evidence:
            risk = "invalid_stable_without_evidence"
            warnings = ["Una neurona stable debe mostrar evidencia de promoción."]
        else:
            risk = "low" if has_evidence else "unknown"
            warnings = [] if has_evidence else [INSUFFICIENT_IDENTITY_MESSAGE]

        return {
            "name": name,
            "type": self._type_for_domain(domain),
            "category": self._type_for_domain(domain),
            "mission": neuron.get("mission") or INSUFFICIENT_IDENTITY_MESSAGE,
            "state": status,
            "status": status,
            "trust_level": round(score, 3),
            "domain": domain,
            "observing": self._observing(neuron),
            "learning_state": self._learning_state(status, has_evidence),
            "learned_or_attempting": self._learned_or_attempting(status, neuron, evidence),
            "last_activity": (activity[0].get("created_at") if activity else None) or evidence.get("last_run_id"),
            "evidence_used": self._evidence_used(evidence, training, qualia),
            "current_risk": risk,
            "warnings": warnings,
            "allowed_effects": list(NEURON_STATUS_EFFECTS.get(status, ("observe", "diagnose"))),
            "triade_relation": {
                "central": self._central_contribution(status, domain),
                "hypothalamus": self._hypothalamus_signal(status),
                "bodega": self._bodega_proposal(status),
                "qualia_bus": self._qualia_contribution(qualia),
            },
            "limits": self._limits(status, neuron),
            "promotion_reason": promotion_reason,
            "stable_promotion_ready": ready_for_stable,
            "readiness": {
                "ready_for_stable_review": ready_for_stable,
                "blockers": readiness.get("blockers", []),
                "required_human_decision": readiness.get("required_human_decision", True),
            },
            "recent_activity": activity,
            "recent_qualia_experiences": qualia,
            "training": training,
            "identity_message": None if has_evidence else INSUFFICIENT_IDENTITY_MESSAGE,
            "policy": "read_only_neuron_identity_view_identity_core_protected",
        }

    @staticmethod
    def _type_for_domain(domain: str) -> str:
        if domain in {"system_governance", "safety", "learning"}:
            return "governance"
        if domain in {"memory", "semantic_memory"}:
            return "memory"
        if domain in {"models", "routing"}:
            return "model_ops"
        return "general"

    @staticmethod
    def _observing(neuron: dict[str, Any]) -> list[str]:
        triggers = neuron.get("triggers") or []
        inputs = neuron.get("inputs_allowed") or []
        return list(dict.fromkeys([str(x) for x in [*triggers, *inputs] if str(x).strip()]))[:8]

    @staticmethod
    def _learning_state(status: str, has_evidence: bool) -> str:
        if status == "candidate":
            return "candidate_limited_pending_evidence"
        if status == "experimental":
            return "hypothesis_testing" if has_evidence else "experimental_without_sufficient_evidence"
        if status in {"trusted_worker", "active_assistant"}:
            return "controlled_assistance_with_traceability"
        if status == "stable":
            return "stable_with_evidence" if has_evidence else "invalid_stable_without_evidence"
        return "unknown"

    @staticmethod
    def _learned_or_attempting(status: str, neuron: dict[str, Any], evidence: dict[str, Any]) -> str:
        mission = str(neuron.get("mission") or "").strip()
        if status == "experimental":
            return f"Como hipótesis, intenta validar: {mission}" if mission else INSUFFICIENT_IDENTITY_MESSAGE
        if status == "candidate":
            return f"Propone observar: {mission}" if mission else INSUFFICIENT_IDENTITY_MESSAGE
        if evidence.get("activation_count"):
            return f"Ha acumulado {evidence.get('activation_count')} activaciones auditables."
        return mission or INSUFFICIENT_IDENTITY_MESSAGE

    @staticmethod
    def _evidence_used(evidence: dict[str, Any], training: list[dict[str, Any]], qualia: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if evidence:
            items.append({"source": evidence.get("source"), "kind": "activity_ledger", "summary": evidence})
        for row in training[:3]:
            items.append({"source": "neuron_training", "kind": "training", "summary": row})
        for row in qualia[:3]:
            items.append({"source": "qualia_bus", "kind": "qualia_hypothesis", "summary": row})
        return items

    @staticmethod
    def _central_contribution(status: str, domain: str) -> str:
        if status in {"candidate", "experimental"}:
            return f"Aporta diagnóstico tentativo sobre {domain}; la Central no lo acepta como hecho."
        return f"Aporta contexto controlado sobre {domain} a la respuesta central."

    @staticmethod
    def _hypothalamus_signal(status: str) -> str:
        if status == "candidate":
            return "Señal débil de necesidad; no altera riesgo por sí sola."
        if status == "experimental":
            return "Señal experimental tratada como hipótesis."
        return "Señal auxiliar permitida por su estado promovido."

    @staticmethod
    def _bodega_proposal(status: str) -> str:
        if status in {"candidate", "experimental"}:
            return "Solo puede proponer memoria experimental; no escribe memoria estable."
        return "Puede proponer aprendizaje, siempre pasando por LearningPipeline y gates."

    @staticmethod
    def _qualia_contribution(qualia: list[dict[str, Any]]) -> str:
        if qualia:
            return f"{len(qualia)} experiencias recientes se tratan como hipótesis Qualia."
        return "Sin experiencias Qualia recientes."

    @staticmethod
    def _limits(status: str, neuron: dict[str, Any]) -> list[str]:
        limits = [
            "No puede modificar identity_core.",
            "No puede escribir memoria estable sin LearningPipeline.",
            "No puede usar shell arbitrario ni red externa obligatoria.",
        ]
        if status == "candidate":
            limits.append("Candidate: solo observa y diagnostica.")
        if status == "experimental":
            limits.append("Experimental: sus aprendizajes son hipótesis.")
        limits.extend(str(x) for x in (neuron.get("forbidden_actions") or [])[:5])
        return list(dict.fromkeys(limits))

    @staticmethod
    def _promotion_reason(status: str, ready_for_stable: bool, evidence: dict[str, Any], training: dict[str, Any]) -> str | None:
        if status == "stable":
            return "Promovida con evidencia suficiente." if ready_for_stable or evidence or training else None
        if status in {"trusted_worker", "active_assistant"}:
            return "Promoción intermedia por contrato y score de entrenamiento." if training else None
        return None

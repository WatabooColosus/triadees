from __future__ import annotations

from pathlib import Path
from typing import Any

from .neuron_registry import NeuronRegistry
from .stable_promotion_readiness import evaluate_stable_readiness, SYNTHETIC_POLICIES


class NeuronAutopromoter:
    """Promoción autónoma de neuronas durante cada ciclo del runner.

    Reglas:
      - candidate → experimental: score >= 0.65 y sin gate bloqueante
      - experimental → stable: readiness thresholds + evidencia diversa
      - stable nunca se degrada
      - Cada decisión incluye razón auditable (incluyendo cuando NO promueve)
    """

    CANDIDATE_TO_EXPERIMENTAL_MIN_SCORE = 0.65
    STABLE_THRESHOLDS = {
        "min_activations": 5,
        "min_diagnosis": 5,
        "min_test_plan": 3,
        "min_non_synthetic_activations": 1,
        "min_external_verifications": 1,
    }

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.registry = NeuronRegistry(db_path=str(self.db_path))

    def promote(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for n in self.registry.list_neurons(limit=100):
            status = (n.get("status") or "").strip().lower()
            name = n.get("name", "?")
            if status in ("candidate_reviewable", "candidate", "experimental_candidate", "weak_candidate"):
                ev = self._promote_candidate_to_experimental(n)
                if ev:
                    events.append(ev)
            elif status == "experimental":
                ev = self._promote_experimental_to_stable(n)
                if ev:
                    events.append(ev)
        return events

    def _promote_candidate_to_experimental(self, n: dict[str, Any]) -> dict[str, Any] | None:
        name = n.get("name", "?")
        training = self.registry.list_training(int(n["id"]), limit=1)
        contract = n.get("contract_json") or {}
        candidate_gate = contract.get("candidate_gate") if isinstance(contract, dict) else {}
        blocked_gate_types = {"factual_simple", "positive_feedback", "thanks", "acknowledgement"}
        if isinstance(candidate_gate, dict) and candidate_gate:
            gate_score = float(candidate_gate.get("score") or 0.0)
            detected_type = str(candidate_gate.get("detected_type") or "").strip().lower()
            if gate_score < self.CANDIDATE_TO_EXPERIMENTAL_MIN_SCORE or detected_type in blocked_gate_types:
                return {
                    "type": "autopromotion_skipped",
                    "severity": "info",
                    "status": "not_promoted",
                    "message": (
                        f"Neurona '{name}' bloqueada por gate de candidato "
                        f"(score={gate_score:.2f}, detected_type={detected_type or 'unknown'})."
                    ),
                    "reason": "blocked_by_neuron_candidate_gate",
                    "payload": {
                        "name": name,
                        "candidate_gate": candidate_gate,
                        "threshold": self.CANDIDATE_TO_EXPERIMENTAL_MIN_SCORE,
                    },
                }
        if not training:
            return {
                "type": "autopromotion_skipped",
                "severity": "info",
                "status": "not_promoted",
                "message": f"Neurona '{name}' sin training; no se promueve.",
                "reason": "no_training_data",
                "payload": {"name": name, "current_status": "candidate"},
            }
        score = training[0].get("score", 0.0)
        if score < self.CANDIDATE_TO_EXPERIMENTAL_MIN_SCORE:
            return {
                "type": "autopromotion_skipped",
                "severity": "info",
                "status": "not_promoted",
                "message": f"Neurona '{name}' score={score:.2f} < {self.CANDIDATE_TO_EXPERIMENTAL_MIN_SCORE}; no se promueve.",
                "reason": "score_below_threshold",
                "payload": {"name": name, "score": score, "threshold": self.CANDIDATE_TO_EXPERIMENTAL_MIN_SCORE},
            }
        ap = n.get("activation_policy") or {}
        if not ap.get("auto_approve", True):
            return {
                "type": "autopromotion_skipped",
                "severity": "info",
                "status": "not_promoted",
                "message": f"Neurona '{name}' auto_approve=False; no se promueve sin aprobación humana.",
                "reason": "auto_approve_disabled",
                "payload": {"name": name, "activation_policy": ap},
            }
        try:
            self.registry.update_status(name, "experimental")
        except KeyError:
            return {
                "type": "autopromotion_skipped",
                "severity": "warning",
                "status": "not_promoted",
                "message": f"Neurona '{name}' no encontrada en registry; no se promueve.",
                "reason": "neuron_not_found",
                "payload": {"name": name},
            }
        return {
            "type": "autopromotion",
            "severity": "important",
            "status": "promoted",
            "message": f"Neurona '{name}' promovida automáticamente de candidate → experimental (score={score:.2f})",
            "action_required": "review_experimental_behavior",
            "payload": {"name": name, "from": "candidate_reviewable", "to": "experimental", "score": score},
        }

    def _promote_experimental_to_stable(self, n: dict[str, Any]) -> dict[str, Any] | None:
        name = n.get("name", "?")
        readiness = evaluate_stable_readiness(prefer_db=True, db_path=str(self.db_path))
        neuron_report = None
        for nr in (readiness.get("neurons") or []):
            if nr.get("name") == name:
                neuron_report = nr
                break

        if not neuron_report:
            return {
                "type": "autopromotion_skipped",
                "severity": "info",
                "status": "not_promoted",
                "message": f"Neurona '{name}' no encontrada en reporte de readiness.",
                "reason": "not_in_readiness_report",
                "payload": {"name": name},
            }

        if not neuron_report.get("ready_for_stable_review"):
            blockers = neuron_report.get("blockers", [])
            return {
                "type": "autopromotion_skipped",
                "severity": "info",
                "status": "not_promoted",
                "message": f"Neurona '{name}' no lista para stable: {'; '.join(blockers[:3])}",
                "reason": "readiness_blockers",
                "payload": {"name": name, "blockers": blockers},
            }

        # Verificar evidencia diversa: al menos 1 activación no sintética
        non_synth = neuron_report.get("non_synthetic_activations", 0)
        if non_synth < self.STABLE_THRESHOLDS["min_non_synthetic_activations"]:
            return {
                "type": "autopromotion_skipped",
                "severity": "info",
                "status": "not_promoted",
                "message": (
                    f"Neurona '{name}' tiene solo evidencia sintética "
                    f"({non_synth} no sintéticas). "
                    "Se requiere evidencia de runs de usuario, tests o workers."
                ),
                "reason": "insufficient_diverse_evidence",
                "payload": {
                    "name": name,
                    "non_synthetic_activations": non_synth,
                    "required": self.STABLE_THRESHOLDS["min_non_synthetic_activations"],
                },
            }

        # Verificar al menos 1 verificación externa (run-* artifact)
        ext_verif = neuron_report.get("external_verifications", 0)
        if ext_verif < self.STABLE_THRESHOLDS["min_external_verifications"]:
            return {
                "type": "autopromotion_skipped",
                "severity": "info",
                "status": "not_promoted",
                "message": (
                    f"Neurona '{name}' sin verificaciones externas suficientes "
                    f"({ext_verif}). Se requiere al menos 1 run real del runner."
                ),
                "reason": "insufficient_external_verification",
                "payload": {
                    "name": name,
                    "external_verifications": ext_verif,
                    "required": self.STABLE_THRESHOLDS["min_external_verifications"],
                },
            }

        try:
            self.registry.update_status(name, "stable")
        except KeyError:
            return {
                "type": "autopromotion_skipped",
                "severity": "warning",
                "status": "not_promoted",
                "message": f"Neurona '{name}' no encontrada en registry al intentar promover a stable.",
                "reason": "neuron_not_found",
                "payload": {"name": name},
            }
        return {
            "type": "autopromotion",
            "severity": "critical",
            "status": "promoted",
            "message": f"Neurona '{name}' promovida de experimental → stable con evidencia diversa verificada.",
            "action_required": "monitor_stable_behavior",
            "payload": {
                "name": name,
                "from": "experimental",
                "to": "stable",
                "readiness": neuron_report,
                "non_synthetic_activations": non_synth,
                "external_verifications": ext_verif,
            },
        }

    def compute_progress(self, neuron: dict[str, Any], training: list[dict[str, Any]]) -> dict[str, Any]:
        status = (neuron.get("status") or "").strip().lower()
        name = neuron.get("name", "?")
        if status in ("stable", "rejected"):
            return {"phase": status, "progress": 1.0, "label": "Completado" if status == "stable" else "Rechazado"}
        if status in ("candidate_reviewable", "candidate"):
            score = training[0].get("score", 0.0) if training else 0.0
            progress = min(score / self.CANDIDATE_TO_EXPERIMENTAL_MIN_SCORE, 1.0)
            return {"phase": "candidate", "progress": progress, "score": score, "threshold": self.CANDIDATE_TO_EXPERIMENTAL_MIN_SCORE, "target": "experimental", "label": f"{score:.0%} hacia experimental"}
        if status == "experimental":
            readiness = evaluate_stable_readiness(db_path=str(self.db_path), prefer_db=True)
            nr = None
            for rn in (readiness.get("neurons") or []):
                if rn.get("name") == name:
                    nr = rn
                    break
            nr = nr or {}
            a = min(int(nr.get("activation_count", 0)) / self.STABLE_THRESHOLDS["min_activations"], 1.0)
            d = min(int(nr.get("diagnosis_count", 0)) / self.STABLE_THRESHOLDS["min_diagnosis"], 1.0)
            t = min(int(nr.get("test_plan_count", 0)) / self.STABLE_THRESHOLDS["min_test_plan"], 1.0)
            progress = round((a + d + t) / 3, 4)
            return {
                "phase": "experimental", "progress": progress,
                "activation_progress": a, "diagnosis_progress": d, "test_plan_progress": t,
                "thresholds": self.STABLE_THRESHOLDS,
                "target": "stable", "label": f"{progress:.0%} hacia stable",
            }
        return {"phase": status, "progress": 0.0, "label": "En espera"}

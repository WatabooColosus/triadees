from __future__ import annotations

from pathlib import Path
from typing import Any

from .neuron_registry import NeuronRegistry
from .stable_promotion_readiness import evaluate_stable_readiness


class NeuronAutopromoter:
    """Promoción autónoma de neuronas durante cada ciclo del runner.

    Reglas:
      - candidate → experimental: score > 0.5, sin riesgo crítico
      - experimental → stable: readiness thresholds cumplidos
      - stable nunca se degrada
    """

    CANDIDATE_TO_EXPERIMENTAL_MIN_SCORE = 0.5
    STABLE_THRESHOLDS = {"min_activations": 5, "min_diagnosis": 5, "min_test_plan": 3}

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.registry = NeuronRegistry(db_path=str(self.db_path))

    def promote(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for n in self.registry.list_neurons(limit=100):
            status = (n.get("status") or "").strip().lower()
            name = n.get("name", "?")
            if status == "candidate_reviewable":
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
        if not training:
            return None
        score = training[0].get("score", 0.0)
        if score < self.CANDIDATE_TO_EXPERIMENTAL_MIN_SCORE:
            return None
        ap = n.get("activation_policy") or {}
        if not ap.get("auto_approve", True):
            return None
        try:
            self.registry.update_status(name, "experimental")
        except KeyError:
            return None
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
        report = readiness.get("report") or {}
        neuron_report = report.get(name) or {}
        if not neuron_report.get("ready_for_stable_review"):
            return None
        try:
            self.registry.update_status(name, "stable")
        except KeyError:
            return None
        return {
            "type": "autopromotion",
            "severity": "important",
            "status": "promoted",
            "message": f"Neurona '{name}' promovida automáticamente de experimental → stable por cumplir thresholds de evidencia.",
            "action_required": "monitor_stable_behavior",
            "payload": {"name": name, "from": "experimental", "to": "stable", "readiness": neuron_report},
        }

    def compute_progress(self, neuron: dict[str, Any], training: list[dict[str, Any]]) -> dict[str, Any]:
        status = (neuron.get("status") or "").strip().lower()
        name = neuron.get("name", "?")
        if status in ("stable", "rejected"):
            return {"phase": status, "progress": 1.0, "label": "Completado" if status == "stable" else "Rechazado"}
        if status == "candidate_reviewable":
            score = training[0].get("score", 0.0) if training else 0.0
            progress = min(score / self.CANDIDATE_TO_EXPERIMENTAL_MIN_SCORE, 1.0)
            return {"phase": "candidate", "progress": progress, "score": score, "threshold": self.CANDIDATE_TO_EXPERIMENTAL_MIN_SCORE, "target": "experimental", "label": f"{score:.0%} hacia experimental"}
        if status == "experimental":
            readiness = evaluate_stable_readiness(db_path=str(self.db_path))
            report = readiness.get("report") or {}
            nr = report.get(name) or {}
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

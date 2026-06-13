"""Executor local para misiones neuronales activas.

Convierte una misión experimental/stable en un ciclo trazable: observa contexto
local, registra evidencia, calcula score y puede proponer aprendizaje.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from triade.core.neuron_missions import (
    NeuronEvidence,
    NeuronMission,
    NeuronMissionStore,
    NeuronScore,
    NeuronWorkCycle,
)
from triade.core.ollama_blood import ollama_blood_policy
from triade.learning.pipeline import LearningPipeline

from .contracts import WorkerRunConfig


ACTIVE_MISSION_STATUSES = {"experimental", "stable"}


class NeuronMissionExecutor:
    """Ejecuta un ciclo seguro y local para una misión neuronal."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.store = NeuronMissionStore(db_path=self.db_path)
        self.learning_pipeline = LearningPipeline(db_path=self.db_path)

    def execute(
        self,
        mission_id: int,
        run_ref: str,
        task_payload: dict[str, Any],
        task_dir: Path,
        config: WorkerRunConfig,
    ) -> dict[str, Any]:
        started = time.monotonic()
        task_dir.mkdir(parents=True, exist_ok=True)
        explicit_blood = isinstance(task_payload.get("ollama_blood"), dict)
        blood = task_payload.get("ollama_blood") if explicit_blood else _degraded_blood()
        blood_policy = ollama_blood_policy("neuron_nutrition", blood)
        blood_result = {
            "ollama_blood_status": blood.get("status"),
            "model_used": blood.get("reasoning_model"),
            "degraded_mode": bool(blood_policy.get("degraded")),
            "cognitive_blood_active": bool(blood.get("cognitive_blood_active")),
        }
        if explicit_blood and not blood_policy.get("allowed"):
            return {
                "status": "blocked",
                "mission_id": mission_id,
                "decision": "blocked_no_ollama_blood",
                "reason": "Ollama Blood no disponible; solo observación segura.",
                "stable_memory_written": False,
                **blood_result,
            }

        mission = self.store.get_mission(int(mission_id))
        if mission is None:
            return {
                "status": "blocked",
                "mission_id": mission_id,
                "decision": "mission_not_found",
                "stable_memory_written": False,
                **blood_result,
            }
        if mission.status not in ACTIVE_MISSION_STATUSES:
            return {
                "status": "blocked",
                "mission_id": mission_id,
                "mission_status": mission.status,
                "decision": "mission_status_not_active",
                "stable_memory_written": False,
                **blood_result,
            }

        recent_cycles = self.store.list_cycles(mission.id or mission_id, limit=5)
        recent_evidence = self.store.list_evidence(mission.id or mission_id, limit=5)
        latest_score = self.store.latest_score(mission.id or mission_id)
        context = self._build_context(mission, run_ref, task_payload, recent_cycles, recent_evidence, latest_score, config)

        work = self._run_local_cycle(context)
        elapsed_ms = int((time.monotonic() - started) * 1000)

        evidence = NeuronEvidence(
            mission_id=mission.id or mission_id,
            neuron_id=mission.neuron_id,
            evidence_type="mission_cycle",
            source="worker",
            content=json.dumps(
                {
                    "diagnosis": work["diagnosis"],
                    "observation": work["observation"],
                    "proposed_learning": work["proposed_learning"],
                    "policy": work["policy"],
                },
                ensure_ascii=False,
            ),
            refs=work["evidence_refs"],
            score=float(work["composite_score"]),
        )
        evidence_id = self.store.record_evidence(evidence)
        evidence_ref = f"mission:{mission.id or mission_id}:evidence:{evidence_id}"

        cycle = NeuronWorkCycle(
            mission_id=mission.id or mission_id,
            neuron_id=mission.neuron_id,
            cycle_type="mission_work",
            input_summary=self._compact(context),
            output_summary=work["observation"],
            evidence_refs=[*work["evidence_refs"], evidence_ref],
            duration_ms=elapsed_ms,
            status="completed",
        )
        cycle_id = self.store.record_cycle(cycle)

        score = NeuronScore(
            mission_id=mission.id or mission_id,
            neuron_id=mission.neuron_id,
            score_type="mission_composite",
            value=float(work["composite_score"]),
            components=work["score_components"],
        )
        score_id = self.store.record_score(score)

        learning_candidate = None
        decision = "observed_scored"
        if work["proposed_learning"] and "propose_learning" in mission.allowed_actions:
            learning_candidate = self.learning_pipeline.ingest(
                content=work["proposed_learning"],
                source_type="tool",
                source_ref=f"mission:{mission.id or mission_id}:run:{run_ref}",
                title=f"Aprendizaje propuesto por misión {mission.title}",
                domain=mission.domain,
                risk_level="low",
            )
            decision = "learning_candidate_proposed"
        elif work["proposed_learning"]:
            decision = "learning_proposal_not_allowed"

        result = {
            "status": "completed",
            "mission_id": mission.id or mission_id,
            "neuron_id": mission.neuron_id,
            "run_ref": run_ref,
            "cycle_id": cycle_id,
            "evidence_id": evidence_id,
            "score_id": score_id,
            "diagnosis": work["diagnosis"],
            "observation": work["observation"],
            "proposed_learning": work["proposed_learning"],
            "evidence_refs": [*work["evidence_refs"], evidence_ref, f"mission:{mission.id or mission_id}:cycle:{cycle_id}"],
            "score_components": work["score_components"],
            "composite_score": work["composite_score"],
            "learning_candidate": learning_candidate,
            "decision": decision,
            "stable_memory_written": False,
            "policy": work["policy"],
            **blood_result,
        }
        (task_dir / "neuron_mission_context.json").write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
        (task_dir / "neuron_mission_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def _build_context(
        self,
        mission: NeuronMission,
        run_ref: str,
        task_payload: dict[str, Any],
        recent_cycles: list[NeuronWorkCycle],
        recent_evidence: list[NeuronEvidence],
        latest_score: NeuronScore | None,
        config: WorkerRunConfig,
    ) -> dict[str, Any]:
        return {
            "run_ref": run_ref,
            "mission": {
                "id": mission.id,
                "title": mission.title,
                "mission": mission.mission,
                "domain": mission.domain,
                "status": mission.status,
                "allowed_sources": mission.allowed_sources,
                "allowed_actions": mission.allowed_actions,
            },
            "task_payload": task_payload,
            "recent_cycles": [cycle.to_dict() for cycle in recent_cycles],
            "recent_evidence": [evidence.to_dict() for evidence in recent_evidence],
            "latest_score": latest_score.to_dict() if latest_score else None,
            "execution_policy": {
                "shell": False,
                "network": False,
                "identity_core_modified": False,
                "stable_memory_written": False,
                "timeout_seconds": config.task_timeout,
            },
        }

    def _run_local_cycle(self, context: dict[str, Any]) -> dict[str, Any]:
        mission = context["mission"]
        actions = set(mission.get("allowed_actions") or [])
        sources = set(mission.get("allowed_sources") or [])
        recent_cycles = context.get("recent_cycles") or []
        recent_evidence = context.get("recent_evidence") or []
        latest_score = context.get("latest_score") or {}

        previous_score = float((latest_score or {}).get("value") or 0.0)
        continuity = min(1.0, 0.45 + 0.08 * len(recent_cycles))
        evidence_density = min(1.0, 0.35 + 0.10 * len(recent_evidence))
        scope_fit = 1.0 if {"observe", "diagnose"}.issubset(actions) else 0.65
        source_fit = 1.0 if "worker" in sources else 0.75
        learning_opportunity = 0.85 if "propose_learning" in actions else 0.35
        prior_bonus = min(0.10, previous_score * 0.10)
        components = {
            "continuity": round(continuity, 3),
            "evidence_density": round(evidence_density, 3),
            "action_scope": round(scope_fit, 3),
            "source_scope": round(source_fit, 3),
            "learning_opportunity": round(learning_opportunity, 3),
            "prior_score_bonus": round(prior_bonus, 3),
        }
        composite = round(
            min(
                1.0,
                (continuity * 0.20)
                + (evidence_density * 0.20)
                + (scope_fit * 0.20)
                + (source_fit * 0.15)
                + (learning_opportunity * 0.15)
                + prior_bonus,
            ),
            3,
        )

        title = str(mission.get("title") or "misión neuronal").strip()
        domain = str(mission.get("domain") or "general").strip()
        mission_text = str(mission.get("mission") or "").strip()
        diagnosis = (
            f"La misión '{title}' puede ejecutar un ciclo local en dominio {domain}; "
            f"acciones habilitadas={sorted(actions)} fuentes habilitadas={sorted(sources)}."
        )
        observation = (
            f"Ciclo local de misión {mission.get('id')} ejecutado sin shell ni red. "
            f"Contexto: {len(recent_cycles)} ciclos previos, {len(recent_evidence)} evidencias previas, score previo {previous_score:.2f}."
        )
        proposed_learning = (
            f"Para la misión '{title}', mantener como hipótesis operacional que {mission_text or 'la misión'} "
            f"debe evaluarse con evidencia local trazable por mission_id y run_ref antes de consolidar memoria estable."
        )
        evidence_refs = [
            f"mission:{mission.get('id')}",
            f"run:{context.get('run_ref')}",
            "worker:neuron_mission_executor",
        ]
        if recent_evidence:
            evidence_refs.append(f"previous_evidence:{recent_evidence[0].get('id')}")
        if recent_cycles:
            evidence_refs.append(f"previous_cycle:{recent_cycles[0].get('id')}")

        return {
            "diagnosis": diagnosis,
            "observation": observation,
            "proposed_learning": proposed_learning,
            "evidence_refs": evidence_refs,
            "score_components": components,
            "composite_score": composite,
            "policy": {
                "shell": False,
                "network": False,
                "identity_core_modified": False,
                "stable_memory_written": False,
            },
        }

    def _compact(self, payload: dict[str, Any], limit: int = 900) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)[:limit]


def _degraded_blood() -> dict[str, Any]:
    return {
        "status": "degraded_no_ollama",
        "ollama_ok": False,
        "cognitive_blood_active": False,
        "reasoning_model": None,
        "can_reason": False,
        "can_embed": False,
        "can_nourish_neurons": False,
        "can_evaluate_learning": False,
        "can_consolidate_stable": False,
        "fallback_mode": True,
    }

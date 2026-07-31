"""Ciclo educativo continuo: diagnostica y prepara aprendizaje verificable."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.learning.evidence_bridge import LearningEvidenceBridge

from .competency_store import CompetencyStore, utc_now
from .curriculum import relevant_material, source_domain
from .spaced_repetition import next_review_for


class NeuronEducationCycle:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.store = CompetencyStore(db_path)
        self.evidence = LearningEvidenceBridge(db_path)

    def run_once(self) -> dict[str, Any]:
        target = self._target()
        if target is None:
            return {"status": "no_target", "learned": False}
        neuron_id = int(target["id"])
        domain = str(target["domain"] or "general")
        objective = str(target["mission"] or target["name"])
        competency = self.store.ensure_competency(
            neuron_id, domain, f"competencia:{domain}"
        )
        curriculum = self.store.ensure_curriculum(
            neuron_id, target.get("mission_id"), domain, objective
        )
        materials = relevant_material(self._candidate_materials(), objective, domain)
        independent = len(
            {source_domain(str(item["source_ref"])) for item in materials}
        )
        refs = [str(item["source_ref"]) for item in materials]
        if independent < 2:
            result = "insufficient_material"
            session = self.store.record_session(
                curriculum_id=str(curriculum["curriculum_id"]),
                neuron_id=neuron_id,
                competency_id=str(competency["competency_id"]),
                # Antes de 2026-07-31: state="material_insufficient" (orden
                # de palabras invertido respecto a result="insufficient_material"
                # para el mismo caso, misma llamada). Filas historicas con
                # state='material_insufficient' quedan intactas; el endpoint
                # /api/governance/education/status y NeuronEducationCard ya
                # suman ambas variantes para no perder el conteo historico.
                state=result,
                material_refs=refs,
                independent_sources=independent,
                lesson={"objective": objective, "status": "not_created"},
                exercise={},
                evaluation={
                    "passed": False,
                    "reason": "two_independent_relevant_sources_required",
                },
                result=result,
            )
            self._schedule(str(competency["competency_id"]), result, success=False)
            return {
                "status": "needs_research",
                "learned": False,
                "neuron": target["name"],
                "domain": domain,
                "independent_sources": independent,
                "material_refs": refs,
                **session,
            }

        lesson = {
            "objective": objective,
            "claims": [str(item["content"])[:280] for item in materials[:3]],
            "candidate_ids": [str(item["candidate_id"]) for item in materials[:3]],
            "provenance": refs,
            "truth_status": "candidate",
        }
        exercise = {
            "type": "retrieval_and_application",
            "prompt": f"Explica y aplica: {objective}",
            "evaluation_role": "independent_required",
        }
        session = self.store.record_session(
            curriculum_id=str(curriculum["curriculum_id"]),
            neuron_id=neuron_id,
            competency_id=str(competency["competency_id"]),
            state="lesson_prepared",
            material_refs=refs,
            independent_sources=independent,
            lesson=lesson,
            exercise=exercise,
            evaluation={
                "passed": False,
                "reason": "independent_evaluation_and_run_application_pending",
            },
            result="uncertain",
        )
        evidence_candidate_id = f"neuron-education:{session['session_id']}"
        evidence = self.evidence.declare_hypothesis(
            evidence_candidate_id,
            hypothesis=f"La lección mejora la competencia de la neurona en {domain}",
            capability=f"neuron:{neuron_id}:{domain}",
            subject_id=str(neuron_id),
            require_regression=True,
        )
        self._schedule(str(competency["competency_id"]), "uncertain", success=False)
        return {
            "status": "lesson_prepared",
            "learned": False,
            "neuron": target["name"],
            "domain": domain,
            "independent_sources": independent,
            "material_refs": refs,
            "learning_evidence_id": evidence.get("id"),
            "learning_evidence_candidate_id": evidence_candidate_id,
            "truth_status": "hypothesis_pending_independent_evaluation",
            **session,
        }

    def status(self) -> dict[str, Any]:
        with self.store.connect() as conn:
            counts: dict[str, int] = {}
            for row in conn.execute(
                "SELECT state,COUNT(*) count FROM neuron_education_sessions GROUP BY state"
            ):
                # Filas anteriores a 2026-07-31 usan 'material_insufficient';
                # filas nuevas usan 'insufficient_material' (mismo caso, ver
                # run_once()). Se fusionan para no fragmentar el conteo.
                key = "insufficient_material" if row["state"] == "material_insufficient" else str(row["state"])
                counts[key] = counts.get(key, 0) + int(row["count"])
            recent = [
                dict(row)
                for row in conn.execute(
                    """SELECT session_id,neuron_id,state,independent_source_count,result,created_at
                FROM neuron_education_sessions ORDER BY created_at DESC LIMIT 20"""
                )
            ]
            due = int(
                conn.execute(
                    "SELECT COUNT(*) FROM neuron_competencies WHERE next_review IS NULL OR next_review<=?",
                    (utc_now(),),
                ).fetchone()[0]
            )
        return {
            "status": "ok",
            "mode": "governed_continuous_education",
            "session_counts": counts,
            "due_competencies": due,
            "recent_sessions": recent,
            "truth_policy": "learned_requires_independent_evaluation_run_application_and_measured_improvement",
        }

    def _target(self) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            row = conn.execute(
                """SELECT n.id,n.name,n.domain,n.mission,m.id mission_id,
                COALESCE(c.retention_score,0) retention_score, c.next_review
                FROM neurons n LEFT JOIN neuron_missions m ON m.neuron_id=n.id
                LEFT JOIN neuron_competencies c ON c.neuron_id=n.id AND c.domain=n.domain
                WHERE n.status='experimental' AND (c.next_review IS NULL OR c.next_review<=?)
                ORDER BY retention_score ASC,n.id ASC LIMIT 1""",
                (utc_now(),),
            ).fetchone()
        return dict(row) if row else None

    def _candidate_materials(self) -> list[dict[str, Any]]:
        # Estados reales del pipeline (triade/learning/pipeline.py):
        # candidate -> evaluated -> internally_checked -> validated_in_runs
        # -> consolidated. 'cross_checked'/'externally_supported' no existen
        # en ningun productor real -- esta consulta nunca podia devolver
        # filas (583/583 candidatos reales en 'internally_checked',
        # confirmado en auditoria 2026-07-31). Se usan los tres niveles
        # post-verificacion, no solo el mas alto, para no exigir mas
        # evidencia de la que el propio pipeline ya considera suficiente
        # para "internally_checked".
        with self.store.connect() as conn:
            rows = conn.execute(
                """SELECT candidate_id,title,content,domain,source_type,source_ref,status
                FROM learning_queue WHERE status IN ('internally_checked','validated_in_runs','consolidated')
                AND source_type IN ('repo','document','web','node') AND source_ref IS NOT NULL
                ORDER BY updated_at DESC LIMIT 300"""
            ).fetchall()
        return [dict(row) for row in rows]

    def _schedule(self, competency_id: str, result: str, *, success: bool) -> None:
        review = next_review_for(result, changing_knowledge=True)
        with self.store.connect() as conn:
            conn.execute(
                """UPDATE neuron_competencies SET last_reviewed=?,next_review=?,
                success_count=success_count+?,failure_count=failure_count+?,updated_at=? WHERE competency_id=?""",
                (
                    utc_now(),
                    review,
                    int(success),
                    int(not success),
                    utc_now(),
                    competency_id,
                ),
            )

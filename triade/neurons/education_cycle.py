"""Ciclo educativo continuo: diagnostica y prepara aprendizaje verificable."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from triade.db import sqlite3
from triade.learning.evidence_bridge import LearningEvidenceBridge

from .competency_store import CompetencyStore, utc_now
from .curriculum import domain_query, relevant_material, source_domain
from .spaced_repetition import next_review_for


class NeuronEducationCycle:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.store = CompetencyStore(db_path)
        self.evidence = LearningEvidenceBridge(db_path)

    def run_once(self, *, force: bool = False, target_neuron_id: int | None = None) -> dict[str, Any]:
        """Ejecuta una lección; ``force`` sólo se usa ante material nuevo."""
        target = self._target(force=force, target_neuron_id=target_neuron_id)
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
        # La búsqueda añade el vocabulario del dominio —el MISMO que usó la
        # investigación— al objetivo de la neurona. Sin él, una neurona nacida
        # de una conversación busca material por la frase que la creó y nunca
        # encuentra lo que se investigó para su dominio.
        busqueda = f"{objective} {domain_query(domain)}"
        candidates = self._candidate_materials()
        materials = relevant_material(candidates, busqueda, domain)
        # Un candidato del mismo dominio es material pertinente aunque su
        # redacción no comparta todos los términos de la consulta. Si el
        # ranking léxico deja el currículo con una sola procedencia, completa
        # el conjunto con otras procedencias del dominio hasta poder evaluar
        # el contraste A/B; nunca mezcla dominios ni inventa fuentes.
        required_sources = self._required_sources()
        if len(materials) < required_sources:
            selected = {str(item.get("candidate_id")) for item in materials}
            for item in candidates:
                if str(item.get("domain") or "") != domain:
                    continue
                if str(item.get("candidate_id")) in selected:
                    continue
                materials.append(item)
                selected.add(str(item.get("candidate_id")))
                if len(materials) >= required_sources:
                    break
        material_sources = {
            source
            for item in materials
            for source in self._material_source_refs(item)
            if source
        }
        independent = len({source_domain(source) for source in material_sources})
        refs = sorted(material_sources)
        if independent < required_sources:
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
                    "reason": "independent_source_threshold_not_met",
                    "required_independent_sources": required_sources,
                    "observed_independent_sources": independent,
                    "ab_contract": "baseline_before_lesson_and_post_after_application",
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
                "required_independent_sources": required_sources,
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
                "required_independent_sources": required_sources,
                "ab_contract": "baseline_before_lesson_and_post_after_application",
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
            "required_independent_sources": required_sources,
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
                key = (
                    "insufficient_material"
                    if row["state"] == "material_insufficient"
                    else str(row["state"])
                )
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

    def _target(
        self, *, force: bool = False, target_neuron_id: int | None = None
    ) -> dict[str, Any] | None:
        """Elige a quién educar, prefiriendo a quien luego se puede medir.

        Ordenaba por `retention_score ASC, n.id ASC`, así que siempre ganaba la
        experimental de menor id. En producción eso significaba las neuronas 11
        y 12, que **sólo se activan en runs `pulse-*`** — y esos runs no generan
        `verification_reports`. Sus lecciones no podían evaluarse nunca:
        `neuron_education_applications` quedaba a cero y el resolutor sólo podía
        responder `insufficient_evidence`. Mientras tanto la neurona 6471, con
        63 runs medibles, no llegaba jamás a `lesson_prepared`.

        Educar a quien nadie puede medir es trabajo perdido: produce lecciones
        que no se pueden certificar ni revertir.

        **Prioriza, no excluye.** Si ninguna evaluable tiene revisión pendiente,
        se sigue educando a la que haya: dejar fuera para siempre a una neurona
        sería otra decisión silenciosa. Lo que cambia es el orden, no el derecho.
        """
        with self.store.connect() as conn:
            tablas = {
                str(r[0])
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            # En una base recién migrada puede no existir todavía la medición.
            # Sin ella el criterio no aplica y se conserva el orden de siempre.
            if {"neuron_activity", "verification_reports"} <= tablas:
                medible = """(SELECT COUNT(DISTINCT na.run_id)
                    FROM neuron_activity na
                    JOIN verification_reports vr ON vr.run_id = na.run_id
                    WHERE na.neuron_id = n.id AND na.activated = 1) > 0"""
            else:
                medible = "0"
            material_priority = (
                "CASE WHEN EXISTS ("
                "SELECT 1 FROM learning_queue lq "
                "WHERE lq.status IN ('internally_checked','validated_in_runs','consolidated') "
                "AND lq.domain = n.domain) THEN 0 ELSE 1 END"
                if "learning_queue" in tablas
                else "CASE WHEN 1=1 THEN 0 ELSE 1 END"
            )
            rows = conn.execute(
                f"""SELECT n.id,n.name,n.domain,n.mission,m.id mission_id,
                COALESCE(c.retention_score,0) retention_score, c.next_review,
                {medible} AS measurable
                FROM neurons n LEFT JOIN neuron_missions m ON m.neuron_id=n.id
                LEFT JOIN neuron_competencies c ON c.neuron_id=n.id AND c.domain=n.domain
                WHERE n.status='experimental'
                  AND (? IS NULL OR n.id=?)
                  AND (? = 1 OR c.next_review IS NULL OR c.next_review<=?)
                ORDER BY
                  {material_priority},
                  measurable DESC, retention_score ASC, n.id ASC LIMIT 1""",
                (target_neuron_id, target_neuron_id, 1 if force else 0, utc_now()),
            ).fetchall()
        candidates = self._candidate_materials()
        for row in rows:
            target = dict(row)
            objective = str(target.get("mission") or target.get("name") or "")
            domain = str(target.get("domain") or "general")
            matched = relevant_material(
                candidates,
                f"{objective} {domain_query(domain)}",
                domain,
            )
            if matched:
                return target
        # Conserva el diagnóstico para neuronas que aún no tienen material;
        # sólo se usa cuando no existe ningún dominio con material relevante.
        return dict(rows[0]) if rows else None

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
            tables = {
                str(r[0])
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "learning_queue" not in tables:
                return []
            rows = conn.execute(
                """SELECT candidate_id,title,content,domain,source_type,source_ref,status
                FROM learning_queue WHERE status IN ('internally_checked','validated_in_runs','consolidated')
                AND source_type IN ('repo','document','web','node','tool','conversation','qualia_bus')
                AND source_ref IS NOT NULL
                ORDER BY updated_at DESC LIMIT 300"""
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _material_source_refs(item: dict[str, Any]) -> set[str]:
        """Recupera la procedencia original de un candidato compuesto.

        La investigación gobernada guarda varias fuentes en el contenido de
        un único candidato (`Fuente: https://...`) y conserva el prefijo
        `research:` como referencia del paquete. Antes sólo se contaba ese
        prefijo, reduciendo cualquier paquete de dos fuentes a una sola.
        """
        refs = {str(item.get("source_ref") or "")}
        content = str(item.get("content") or "")
        refs.update(re.findall(r"https?://[^\s)]+", content))
        return {ref.rstrip(".,;\"]'") for ref in refs if ref}

    def _required_sources(self) -> int:
        """Deriva N de necesidades metabólicas activas, con límites seguros.

        Una necesidad aislada exige dos fuentes independientes; cuando el
        metabolismo mantiene varias necesidades activas, el umbral crece hasta
        cinco. Así el currículo se adapta al estado del organismo sin poder
        exigir una cantidad infinita ni saltarse el contraste A-B.
        """
        try:
            with self.store.connect() as conn:
                row = conn.execute(
                    """SELECT COUNT(*) AS n FROM metabolic_needs
                       WHERE status IN ('pending','authorized','running','queued')"""
                ).fetchone()
                active = int(row["n"] or 0) if row else 0
        except (sqlite3.Error, OSError, TypeError, ValueError):
            active = 0
        return max(2, min(5, active or 2))

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

"""Produce evidencia causal para un candidato: control contra tratamiento.

Es la pieza que faltaba. `EvidenceBridge.require_improvement()` es un gate
correcto y estricto —exige baseline, candidate, comparison, reporte de
regresión y cero regresiones críticas— pero nadie lo alimentaba. Por eso los
633 candidatos llevaban meses en `internally_checked`.

Aquí no se baja ningún requisito. Se ejecutan pares reales:

- CONTROL     — la pregunta sin el candidato en contexto.
- TRATAMIENTO — la misma pregunta, mismo modelo, mismas `options`, con el
  candidato inyectado **antes** de generar.

Un candidato que no llegó a inyectarse no puede declararse usado, por muy
parecida que sea la respuesta: el modelo puede saberlo de antes.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import statistics
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from triade.evaluation.contracts import (
    EvaluationComparison,
    EvaluationRun,
    MetricResult,
)
from triade.learning.evidence_bridge import LearningEvidenceBridge
from triade.learning.retrieval import LearningRetriever, build_learning_block
from triade.regression.gate import MetricPolicy, RegressionGate

PRODUCER_VERSION = "evidence-producer-1.0.0"
SUITE_ID = "learning-causal-suite"
SUITE_VERSION = "1.0.0"

Decision = Literal[
    "pending",
    "evaluating",
    "improved",
    "unchanged",
    "regressed",
    "inconclusive",
    "blocked",
    "invalid",
    "failed",
]

MIN_REPETITIONS = 5


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


@dataclass
class EvidenceOutcome:
    evidence_id: str
    candidate_id: str
    candidate_version: str
    candidate_hash: str
    source_run_ids: list[str] = field(default_factory=list)
    control_run_ids: list[str] = field(default_factory=list)
    treatment_run_ids: list[str] = field(default_factory=list)
    control_prompt_hashes: list[str] = field(default_factory=list)
    treatment_prompt_hashes: list[str] = field(default_factory=list)
    model_id: str = ""
    temperature: float = 0.0
    seed: int = 0
    repetitions: int = 0
    deterministic_scores: dict[str, list[float]] = field(default_factory=dict)
    control_mean: float = 0.0
    treatment_mean: float = 0.0
    absolute_delta: float = 0.0
    regression_report_id: str | None = None
    suite_id: str = SUITE_ID
    suite_version: str = SUITE_VERSION
    decision: Decision = "pending"
    evidence_refs: list[str] = field(default_factory=list)
    reason: str = ""
    created_at: str = field(default_factory=_utc_now)
    producer_version: str = PRODUCER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LearningEvidenceProducer:
    """Ejecuta la comparación causal y persiste evidencia completa."""

    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        *,
        generate: Callable[[str], str],
        model_id: str = "qwen2.5:3b-instruct",
        temperature: float = 0.0,
        seed: int = 7731,
    ) -> None:
        self.db_path = Path(db_path)
        self.generate = generate
        self.model_id = model_id
        self.temperature = temperature
        self.seed = seed
        self.retriever = LearningRetriever(db_path=db_path)
        self.bridge = LearningEvidenceBridge(db_path=db_path)
        self.gate = RegressionGate(db_path=db_path)

    # ── ejecución ────────────────────────────────────────────────────
    def produce(
        self,
        *,
        candidate_id: str,
        question: str,
        evaluator: Callable[[str], bool],
        capability: str = "conversational_learning",
        repetitions: int = MIN_REPETITIONS,
        source_run_ids: list[str] | None = None,
    ) -> EvidenceOutcome:
        outcome = EvidenceOutcome(
            evidence_id=f"ev-{uuid.uuid4().hex[:16]}",
            candidate_id=candidate_id,
            candidate_version="",
            candidate_hash="",
            source_run_ids=source_run_ids or [],
            model_id=self.model_id,
            temperature=self.temperature,
            seed=self.seed,
            repetitions=repetitions,
        )

        if repetitions < MIN_REPETITIONS:
            outcome.decision = "inconclusive"
            outcome.reason = (
                f"insufficient_evidence: {repetitions} repeticiones, "
                f"mínimo {MIN_REPETITIONS}"
            )
            self._record_attempt(outcome, capability)
            return outcome

        # ¿El candidato puede siquiera inyectarse? Si el filtro de seguridad lo
        # retiene, no hay experimento que hacer: hay un bloqueo que registrar.
        sonda = self.retriever.retrieve_decision(
            question,
            run_id=f"{outcome.evidence_id}-probe",
            only_candidate_ids={candidate_id},
        )
        if candidate_id not in sonda.injected_ids:
            outcome.decision = "blocked"
            outcome.reason = self._block_reason(sonda, candidate_id)
            self._record_attempt(outcome, capability)
            return outcome

        match = sonda.matches[0]
        outcome.candidate_version = match.candidate_version
        outcome.candidate_hash = match.content_hash

        aciertos_control: list[float] = []
        aciertos_tratamiento: list[float] = []

        for i in range(repetitions):
            # Se alterna el orden para que ningún grupo se beneficie siempre de
            # ir primero (caché del modelo, calentamiento, deriva de carga).
            orden = ("control", "treatment") if i % 2 == 0 else ("treatment", "control")
            for grupo in orden:
                prompt, decision_r = self._build_prompt(
                    question, candidate_id, grupo, f"{outcome.evidence_id}-{grupo}-{i}"
                )
                if grupo == "treatment" and candidate_id not in decision_r.injected_ids:
                    outcome.decision = "invalid"
                    outcome.reason = "treatment_sin_inyeccion"
                    return outcome
                if grupo == "control" and candidate_id in decision_r.injected_ids:
                    outcome.decision = "invalid"
                    outcome.reason = "control_contaminado"
                    return outcome

                respuesta = self.generate(prompt)
                acierto = 1.0 if evaluator(respuesta) else 0.0
                run_id = f"{outcome.evidence_id}-{grupo}-{i}"
                if grupo == "control":
                    aciertos_control.append(acierto)
                    outcome.control_run_ids.append(run_id)
                    outcome.control_prompt_hashes.append(_sha(prompt))
                else:
                    aciertos_tratamiento.append(acierto)
                    outcome.treatment_run_ids.append(run_id)
                    outcome.treatment_prompt_hashes.append(_sha(prompt))

        outcome.deterministic_scores = {
            "control": aciertos_control,
            "treatment": aciertos_tratamiento,
        }
        outcome.control_mean = round(statistics.mean(aciertos_control), 4)
        outcome.treatment_mean = round(statistics.mean(aciertos_tratamiento), 4)
        outcome.absolute_delta = round(outcome.treatment_mean - outcome.control_mean, 4)

        return self._decide_and_persist(outcome, capability, question)

    def _record_attempt(self, outcome: EvidenceOutcome, capability: str) -> None:
        """Persiste un intento que terminó sin comparación.

        Sin esto el candidato queda igual que antes de intentarlo y el planner
        lo vuelve a elegir para siempre (F-037). Que falle el registro no puede
        tumbar la tarea: el veredicto es información, no el trabajo.
        """
        try:
            self.bridge.record_inconclusive(
                outcome.candidate_id,
                decision=outcome.decision,
                reason=outcome.reason,
                capability=capability,
            )
        except (ValueError, sqlite3.Error):
            pass

    @staticmethod
    def _block_reason(decision: Any, candidate_id: str) -> str:
        for s in decision.skipped:
            if s.get("candidate_id") == candidate_id:
                return f"blocked:{s.get('reason')}"
        return "blocked:no_elegible"

    def _same_run_candidates(self, candidate_id: str) -> set[str]:
        """Todo lo que salió del mismo run que el candidato medido.

        Un run genera hoy dos filas: la proposición atómica que extrae el camino
        gobernado y el volcado de la transcripción que escribe el camino
        antiguo — y ese volcado **contiene la frase original con el dato
        dentro**. Excluyendo solo el candidato bajo medición, el hermano seguía
        siendo recuperable y el brazo de control recibía la respuesta: acertaba
        5 de 5 y toda medición salía `neutral`. Es la razón de que 349
        generaciones de evidencia no produjeran ni un saber.

        Un experimento sobre un run no puede usar como control nada derivado de
        ese mismo run.
        """
        try:
            with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as conn:
                conn.row_factory = sqlite3.Row
                fila = conn.execute(
                    "SELECT source_ref FROM learning_queue WHERE candidate_id=?",
                    (candidate_id,),
                ).fetchone()
                if fila is None or not str(fila["source_ref"] or "").strip():
                    return {candidate_id}
                hermanos = conn.execute(
                    "SELECT candidate_id FROM learning_queue WHERE source_ref=?",
                    (str(fila["source_ref"]),),
                ).fetchall()
        except sqlite3.Error:
            # Sin poder resolver los hermanos no se puede garantizar un control
            # limpio. Se excluye lo que se sabe y la contaminación la detecta
            # igualmente la comprobación de `_build_prompt`.
            return {candidate_id}
        return {str(r["candidate_id"]) for r in hermanos} | {candidate_id}

    def _build_prompt(
        self, question: str, candidate_id: str, grupo: str, run_id: str
    ) -> tuple[str, Any]:
        if grupo == "control":
            decision = self.retriever.retrieve_decision(
                question,
                run_id=run_id,
                exclude_candidate_ids=self._same_run_candidates(candidate_id),
            )
        else:
            decision = self.retriever.retrieve_decision(
                question, run_id=run_id, only_candidate_ids={candidate_id}
            )
        bloque = build_learning_block(decision.matches)
        prefijo = f"{bloque}\n\n" if bloque else ""
        prompt = (
            f"{prefijo}Pregunta: {question}\n"
            "Responde de forma breve y directa, sin explicaciones."
        )
        return prompt, decision

    # ── decisión y persistencia ──────────────────────────────────────
    def _decide_and_persist(
        self, outcome: EvidenceOutcome, capability: str, question: str
    ) -> EvidenceOutcome:
        baseline = self._evaluation_run(
            f"{outcome.evidence_id}-baseline",
            outcome.candidate_id,
            outcome.control_mean,
        )
        candidate_eval = self._evaluation_run(
            f"{outcome.evidence_id}-candidate",
            outcome.candidate_id,
            outcome.treatment_mean,
        )

        if outcome.absolute_delta > 0:
            decision: Decision = "improved"
        elif outcome.absolute_delta < 0:
            decision = "regressed"
        else:
            decision = "unchanged"

        comparison = EvaluationComparison(
            baseline_evaluation_id=baseline.evaluation_id,
            candidate_evaluation_id=candidate_eval.evaluation_id,
            baseline_score=outcome.control_mean,
            candidate_score=outcome.treatment_mean,
            absolute_delta=outcome.absolute_delta,
            percent_delta=None,
            improved_cases=("learning_recall",) if decision == "improved" else (),
            degraded_cases=("learning_recall",) if decision == "regressed" else (),
            critical_regressions=(),
            decision="improved"
            if decision == "improved"
            else ("regressed" if decision == "regressed" else "neutral"),
        )

        self.bridge.declare_hypothesis(
            outcome.candidate_id,
            hypothesis=f"El candidato mejora la respuesta a: {question[:120]}",
            capability=capability,
            subject_id=outcome.candidate_id,
            require_regression=True,
        )
        self.bridge.record_comparison(
            outcome.candidate_id,
            baseline=baseline,
            candidate=candidate_eval,
            comparison=comparison,
            artifact_ref=outcome.evidence_id,
        )

        # El gate se ejecuta siempre, también cuando el resultado es malo: es
        # la única forma de que un `regressed` quede registrado como tal.
        report = self.gate.evaluate(
            report_id=f"rep-{outcome.evidence_id}",
            candidate_id=outcome.candidate_id,
            capability=capability,
            baseline=baseline,
            candidate=candidate_eval,
            policies=(
                MetricPolicy(
                    metric_id="learning_recall",
                    severity="high",
                    max_absolute_drop=0.0,
                    required=True,
                ),
            ),
            metadata={
                "producer_version": PRODUCER_VERSION,
                "repetitions": outcome.repetitions,
                "model_id": outcome.model_id,
            },
        )
        outcome.regression_report_id = report.report_id
        outcome.evidence_refs = [
            outcome.evidence_id,
            report.report_id,
            *outcome.control_run_ids[:1],
            *outcome.treatment_run_ids[:1],
        ]

        # Sólo `pass` promociona. Un `warn` es un aviso, no un permiso.
        if decision == "improved" and report.decision != "pass":
            decision = "blocked"
            outcome.reason = f"regression_gate:{report.decision}"
        elif decision == "improved":
            self.bridge.record_regression_report(outcome.candidate_id, report)

        outcome.decision = decision
        return outcome

    @staticmethod
    def _evaluation_run(
        evaluation_id: str, subject_id: str, score: float
    ) -> EvaluationRun:
        return EvaluationRun(
            evaluation_id=evaluation_id,
            suite_id=SUITE_ID,
            suite_version=SUITE_VERSION,
            subject_id=subject_id,
            results=(
                MetricResult(
                    case_id="learning_recall",
                    score=score,
                    passed=score > 0,
                    actual=score,
                    expected=1.0,
                ),
            ),
            aggregate_score=score,
            created_at=_utc_now(),
            metadata={"producer_version": PRODUCER_VERSION},
        )

    # ── consolidación gobernada ──────────────────────────────────────
    def promote_if_verified(self, candidate_id: str) -> dict[str, Any]:
        """Sube a `evidence_verified` sólo lo que el gate deja pasar.

        No toca `stable`: eso exige la vía gobernada con firma humana. Aquí sólo
        se reconoce que el efecto está medido y no hubo regresiones.
        """
        try:
            evidencia = self.bridge.require_improvement(candidate_id)
        except ValueError as exc:
            return {"promoted": False, "reason": str(exc)}

        import sqlite3

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE learning_queue SET status = 'evidence_verified',"
                " updated_at = ? WHERE candidate_id = ?",
                (_utc_now(), candidate_id),
            )
        return {
            "promoted": True,
            "candidate_id": candidate_id,
            "decision": evidencia.get("decision"),
            "regression_report_id": evidencia.get("regression_report_id"),
        }


def evidence_payload(outcome: EvidenceOutcome) -> str:
    return json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2)

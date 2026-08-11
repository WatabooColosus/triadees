"""Persistencia de competencias, currículos y sesiones educativas."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from triade.db import sqlite3


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class CompetencyStore:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        migration = (
            Path(__file__).resolve().parents[1]
            / "memory/migrations/010_neuron_education.sql"
        )
        evidence_migration = (
            Path(__file__).resolve().parents[1]
            / "memory/migrations/011_neuron_education_evidence.sql"
        )
        with self.connect() as conn:
            conn.executescript(migration.read_text(encoding="utf-8"))
            conn.executescript(evidence_migration.read_text(encoding="utf-8"))

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def ensure_competency(
        self, neuron_id: int, domain: str, name: str
    ) -> dict[str, Any]:
        now = utc_now()
        competency_id = f"competency-{uuid4().hex[:16]}"
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO neuron_competencies
                (competency_id,neuron_id,domain,name,created_at,updated_at) VALUES(?,?,?,?,?,?)""",
                (competency_id, neuron_id, domain, name, now, now),
            )
            row = conn.execute(
                "SELECT * FROM neuron_competencies WHERE neuron_id=? AND domain=? AND name=?",
                (neuron_id, domain, name),
            ).fetchone()
        return dict(row) if row else {}

    def ensure_curriculum(
        self, neuron_id: int, mission_id: int | None, domain: str, objective: str
    ) -> dict[str, Any]:
        now = utc_now()
        curriculum_id = f"curriculum-{uuid4().hex[:16]}"
        allowed = json.dumps(["repo", "document", "web", "node"], ensure_ascii=False)
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO neuron_curricula
                (curriculum_id,neuron_id,mission_id,domain,objective,allowed_source_types_json,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,'candidate',?,?)""",
                (
                    curriculum_id,
                    neuron_id,
                    mission_id,
                    domain,
                    objective,
                    allowed,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM neuron_curricula WHERE neuron_id=? AND domain=?",
                (neuron_id, domain),
            ).fetchone()
        return dict(row) if row else {}

    def record_session(
        self,
        *,
        curriculum_id: str,
        neuron_id: int,
        competency_id: str,
        state: str,
        material_refs: list[str],
        independent_sources: int,
        lesson: dict[str, Any],
        exercise: dict[str, Any],
        evaluation: dict[str, Any],
        result: str,
        baseline_score: float | None = None,
        post_score: float | None = None,
    ) -> dict[str, Any]:
        session_id = f"education-{uuid4().hex[:16]}"
        now = utc_now()
        rollback_ref = f"education_session:{session_id}:archive_only"
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO neuron_education_sessions
                (session_id,curriculum_id,neuron_id,competency_id,state,material_refs_json,independent_source_count,
                 lesson_json,exercise_json,evaluation_json,baseline_score,post_score,result,rollback_ref,created_at,finished_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    session_id,
                    curriculum_id,
                    neuron_id,
                    competency_id,
                    state,
                    json.dumps(material_refs),
                    independent_sources,
                    json.dumps(lesson, ensure_ascii=False),
                    json.dumps(exercise, ensure_ascii=False),
                    json.dumps(evaluation, ensure_ascii=False),
                    baseline_score,
                    post_score,
                    result,
                    rollback_ref,
                    now,
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO neuron_education_events(session_id,neuron_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",
                (
                    session_id,
                    neuron_id,
                    state,
                    json.dumps({"result": result, "sources": independent_sources}),
                    now,
                ),
            )
        return {
            "session_id": session_id,
            "state": state,
            "result": result,
            "rollback_ref": rollback_ref,
        }

    def record_independent_evaluation(
        self,
        session_id: str,
        *,
        evaluator_id: str,
        baseline_score: float,
        post_score: float,
        evidence_ref: str,
        minimum_improvement: float = 0.05,
    ) -> dict[str, Any]:
        """Registra una evaluación producida fuera del ciclo formador."""
        evaluator = evaluator_id.strip()
        evidence = evidence_ref.strip()
        if not evaluator or evaluator in {"education_cycle", "neuron_formadora"}:
            raise ValueError(
                "La evaluación debe proceder de un evaluador independiente"
            )
        if not evidence:
            raise ValueError("La evaluación requiere evidence_ref trazable")
        if not 0.0 <= baseline_score <= 1.0 or not 0.0 <= post_score <= 1.0:
            raise ValueError("Los scores deben estar entre 0 y 1")
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM neuron_education_sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Sesión inexistente: {session_id}")
            if row["state"] != "lesson_prepared":
                raise ValueError(
                    f"La sesión no está lista para evaluación: {row['state']}"
                )
            improvement = round(post_score - baseline_score, 6)
            passed = improvement >= minimum_improvement
            state = "evaluated_candidate" if passed else "evaluation_rejected"
            result = (
                "passed_pending_run_application"
                if passed
                else "rejected_no_improvement"
            )
            evaluation = {
                "passed": passed,
                "evaluator_id": evaluator,
                "evidence_ref": evidence,
                "baseline_score": baseline_score,
                "post_score": post_score,
                "improvement": improvement,
                "minimum_improvement": minimum_improvement,
                "truth_status": "independently_evaluated_not_yet_learned",
            }
            now = utc_now()
            conn.execute(
                """UPDATE neuron_education_sessions SET state=?,evaluation_json=?,baseline_score=?,
                post_score=?,result=?,finished_at=? WHERE session_id=?""",
                (
                    state,
                    json.dumps(evaluation, ensure_ascii=False),
                    baseline_score,
                    post_score,
                    result,
                    now,
                    session_id,
                ),
            )
            conn.execute(
                "INSERT INTO neuron_education_events(session_id,neuron_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",
                (
                    session_id,
                    int(row["neuron_id"]),
                    state,
                    json.dumps(evaluation, ensure_ascii=False),
                    now,
                ),
            )
        return {
            "session_id": session_id,
            "state": state,
            "result": result,
            "learned": False,
            "evaluation": evaluation,
        }

    def record_run_application(
        self,
        session_id: str,
        *,
        run_id: str,
        outcome_score: float,
        evidence_ref: str,
        minimum_uses: int = 3,
        minimum_average: float = 0.70,
    ) -> dict[str, Any]:
        """Cuenta una aplicación única y solo valida tras evidencia repetida."""
        if not run_id.strip() or not evidence_ref.strip():
            raise ValueError("run_id y evidence_ref son obligatorios")
        if not 0.0 <= outcome_score <= 1.0:
            raise ValueError("outcome_score debe estar entre 0 y 1")
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM neuron_education_sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Sesión inexistente: {session_id}")
            if row["state"] not in {"evaluated_candidate", "validated_in_runs"}:
                raise ValueError(
                    f"La sesión no superó evaluación independiente: {row['state']}"
                )
            before = conn.total_changes
            conn.execute(
                """INSERT OR IGNORE INTO neuron_education_applications
                (session_id,run_id,outcome_score,evidence_ref,created_at) VALUES(?,?,?,?,?)""",
                (
                    session_id,
                    run_id.strip(),
                    outcome_score,
                    evidence_ref.strip(),
                    utc_now(),
                ),
            )
            duplicate = conn.total_changes == before
            aggregate = conn.execute(
                """SELECT COUNT(*) uses,AVG(outcome_score) average
                FROM neuron_education_applications WHERE session_id=?""",
                (session_id,),
            ).fetchone()
            uses = int(aggregate["uses"])
            average = float(aggregate["average"] or 0.0)
            learned = uses >= minimum_uses and average >= minimum_average
            state = "validated_in_runs" if learned else "evaluated_candidate"
            result = (
                "learned_with_measured_run_evidence"
                if learned
                else "pending_more_run_evidence"
            )
            now = utc_now()
            conn.execute(
                """UPDATE neuron_education_sessions SET state=?,applied_run_count=?,post_score=?,
                result=?,finished_at=? WHERE session_id=?""",
                (state, uses, average, result, now, session_id),
            )
            if learned:
                conn.execute(
                    """UPDATE neuron_competencies SET status='validated_in_runs',confidence=?,
                    retention_score=?,success_count=success_count+1,last_reviewed=?,updated_at=?
                    WHERE competency_id=?""",
                    (average, average, now, now, str(row["competency_id"])),
                )
            conn.execute(
                "INSERT INTO neuron_education_events(session_id,neuron_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",
                (
                    session_id,
                    int(row["neuron_id"]),
                    "run_application",
                    json.dumps(
                        {
                            "run_id": run_id,
                            "score": outcome_score,
                            "evidence_ref": evidence_ref,
                            "duplicate": duplicate,
                            "uses": uses,
                            "average": average,
                        },
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )
        return {
            "session_id": session_id,
            "state": state,
            "result": result,
            "learned": learned,
            "applied_run_count": uses,
            "average_outcome_score": round(average, 3),
            "duplicate": duplicate,
        }

    def record_candidate_application(
        self, candidate_id: str, *, run_id: str, outcome_score: float, evidence_ref: str
    ) -> list[dict[str, Any]]:
        """Conecta un candidato usado explícitamente con sesiones ya evaluadas."""
        applications: list[dict[str, Any]] = []
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT session_id,lesson_json FROM neuron_education_sessions
                WHERE state IN ('evaluated_candidate','validated_in_runs')"""
            ).fetchall()
        for row in rows:
            try:
                lesson = json.loads(str(row["lesson_json"] or "{}"))
            except (json.JSONDecodeError, TypeError):
                continue
            candidate_ids = {str(item) for item in lesson.get("candidate_ids", [])}
            if candidate_id not in candidate_ids:
                continue
            applications.append(
                self.record_run_application(
                    str(row["session_id"]),
                    run_id=run_id,
                    outcome_score=outcome_score,
                    evidence_ref=evidence_ref,
                )
            )
        return applications

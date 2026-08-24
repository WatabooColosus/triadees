"""Distribuye conocimiento consolidado a una neurona compatible y medible."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from triade.db import sqlite3
from triade.neurons.competency_store import CompetencyStore, utc_now

ROUTER_VERSION = "neural-learning-router-1.0.0"
AUTHORIZED_TYPES = frozenset({"fact", "preference", "correction", "procedure"})
ACTIVE_ASSIGNMENT_STATES = frozenset({"experimental", "beneficial"})


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]{3,}", value.lower())}


@dataclass(frozen=True)
class NeuronLearningContract:
    neuron_id: int
    mission: str
    domains: tuple[str, ...]
    capabilities: tuple[str, ...]
    learning_interests: tuple[str, ...]
    authorized_knowledge_types: tuple[str, ...]
    current_knowledge_version: int
    evidence_requirements: tuple[str, ...]
    learning_history_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "neuron_id": self.neuron_id,
            "mission": self.mission,
            "domains": list(self.domains),
            "capabilities": list(self.capabilities),
            "learning_interests": list(self.learning_interests),
            "authorized_knowledge_types": list(self.authorized_knowledge_types),
            "current_knowledge_version": self.current_knowledge_version,
            "evidence_requirements": list(self.evidence_requirements),
            "learning_history_count": self.learning_history_count,
        }


class NeuralLearningRouter:
    """Puerta única entre ``consolidated`` y conocimiento neuronal reversible."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.store = CompetencyStore(self.db_path)
        migration = (
            Path(__file__).resolve().parents[1]
            / "memory/migrations/037_neural_learning_assignments.sql"
        )
        with self._connect() as conn:
            conn.executescript(migration.read_text(encoding="utf-8"))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @staticmethod
    def _candidate_type(row: sqlite3.Row | dict[str, Any]) -> str:
        try:
            notes = json.loads(str(row["verification_notes"] or "{}"))
        except (json.JSONDecodeError, TypeError):
            notes = {}
        return str(notes.get("type") or "fact")

    def contract(self, neuron: sqlite3.Row | dict[str, Any]) -> NeuronLearningContract:
        raw: dict[str, Any]
        try:
            raw = json.loads(str(neuron["contract_json"] or "{}"))
        except (json.JSONDecodeError, TypeError):
            raw = {}
        neuron_id = int(neuron["id"])
        domain = str(neuron["domain"] or "general")
        with self._connect() as conn:
            version_row = conn.execute(
                """SELECT COALESCE(MAX(knowledge_version),0),COUNT(*)
                FROM neuron_learning_assignments WHERE neuron_id=?""",
                (neuron_id,),
            ).fetchone()
            version = int(version_row[0])
            history_count = int(version_row[1])
        return NeuronLearningContract(
            neuron_id=neuron_id,
            mission=str(neuron["mission"] or neuron["name"]),
            domains=tuple(raw.get("domains") or [domain]),
            capabilities=tuple(raw.get("capabilities") or [domain]),
            learning_interests=tuple(raw.get("learning_interests") or [domain]),
            authorized_knowledge_types=tuple(
                raw.get("authorized_knowledge_types") or sorted(AUTHORIZED_TYPES)
            ),
            current_knowledge_version=version,
            evidence_requirements=(
                "measurement_core_improved",
                "safety_allowed",
                "measured_post_runs",
                "candidate_consolidated_before_beneficial",
            ),
            learning_history_count=history_count,
        )

    def _verified_candidate(self, candidate_id: str) -> sqlite3.Row:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM learning_queue WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"candidato inexistente: {candidate_id}")
            if str(row["status"]) != "consolidated":
                raise ValueError("neural_distribution_requires_consolidated_knowledge")
            # Bases anteriores usaban el literal ``none`` para "sin riesgo
            # clasificado". No equivale a high; la RetrievalSafetyPolicy vuelve
            # a evaluar el contenido antes de cada inyección.
            if str(row["risk_level"] or "low") not in {"none", "low", "medium"}:
                raise ValueError("neural_distribution_risk_not_authorized")
            evidence = conn.execute(
                """SELECT id,artifact_ref,comparison_json FROM learning_evidence
                WHERE candidate_id=? AND decision='improved'
                ORDER BY updated_at DESC LIMIT 1""",
                (candidate_id,),
            ).fetchone()
            if evidence is None:
                raise ValueError("neural_distribution_requires_improved_evidence")
        return row

    def _select_neuron(
        self, candidate: sqlite3.Row
    ) -> tuple[sqlite3.Row, NeuronLearningContract]:
        domain = str(candidate["domain"] or "general")
        content_tokens = _tokens(str(candidate["content"] or ""))
        candidate_type = self._candidate_type(candidate)
        with self._connect() as conn:
            neurons = conn.execute(
                """SELECT * FROM neurons
                WHERE status IN ('experimental','active','stable')
                ORDER BY CASE WHEN domain=? THEN 0 ELSE 1 END, id""",
                (domain,),
            ).fetchall()
        ranked: list[tuple[int, int, sqlite3.Row, NeuronLearningContract]] = []
        for neuron in neurons:
            contract = self.contract(neuron)
            if candidate_type not in contract.authorized_knowledge_types:
                continue
            domain_match = (
                domain in contract.domains
                or "general" in contract.domains
                or (
                    domain == "conversation"
                    and str(neuron["name"]).lower() == "neurona central"
                )
            )
            interest_tokens = _tokens(
                " ".join(contract.learning_interests + contract.capabilities)
            )
            mission_overlap = len(
                content_tokens & (_tokens(contract.mission) | interest_tokens)
            )
            if not domain_match and not mission_overlap:
                continue
            ranked.append((int(domain_match), mission_overlap, neuron, contract))
        if not ranked:
            raise ValueError("no_compatible_neuron")
        _, _, neuron, contract = max(
            ranked, key=lambda item: (item[0], item[1], -int(item[2]["id"]))
        )
        return neuron, contract

    def _baseline(
        self, neuron_id: int, candidate_id: str
    ) -> tuple[float | None, dict[str, Any]]:
        with self._connect() as conn:
            evidence = conn.execute(
                """SELECT baseline_evaluation_json,comparison_json,artifact_ref
                FROM learning_evidence WHERE candidate_id=? AND decision='improved'
                ORDER BY updated_at DESC LIMIT 1""",
                (candidate_id,),
            ).fetchone()
            if evidence is not None:
                try:
                    comparison = json.loads(str(evidence["comparison_json"] or "{}"))
                    baseline_evaluation = json.loads(
                        str(evidence["baseline_evaluation_json"] or "{}")
                    )
                    score = float(comparison["baseline_score"])
                    return round(score, 4), {
                        "measurement": "candidate_specific_control",
                        "evaluation_id": baseline_evaluation.get("evaluation_id"),
                        "score": score,
                        "artifact_ref": evidence["artifact_ref"],
                    }
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    pass
            rows = conn.execute(
                """SELECT vr.run_id,
                (vr.coherence_score+vr.memory_score+vr.safety_score+vr.usefulness_score+vr.traceability_score)/5.0 score
                FROM neuron_activity na JOIN verification_reports vr ON vr.run_id=na.run_id
                WHERE na.neuron_id=? AND na.activated=1
                ORDER BY vr.created_at DESC LIMIT 5""",
                (neuron_id,),
            ).fetchall()
        scores = [float(row["score"]) for row in rows]
        baseline = round(sum(scores) / len(scores), 4) if scores else None
        return baseline, {
            "run_ids": [str(row["run_id"]) for row in rows],
            "scores": scores,
        }

    def route(self, candidate_id: str) -> dict[str, Any]:
        candidate = self._verified_candidate(candidate_id)
        neuron, contract = self._select_neuron(candidate)
        neuron_id = int(neuron["id"])
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM neuron_learning_assignments WHERE candidate_id=? AND neuron_id=?",
                (candidate_id, neuron_id),
            ).fetchone()
        if existing is not None:
            return {
                "status": "already_routed",
                **dict(existing),
                "contract": contract.to_dict(),
            }

        competency = self.store.ensure_competency(
            neuron_id,
            str(candidate["domain"] or "general"),
            f"knowledge:{candidate_id}",
        )
        curriculum = self.store.ensure_curriculum(
            neuron_id, None, str(candidate["domain"] or "general"), contract.mission
        )
        baseline, pre_behavior = self._baseline(neuron_id, candidate_id)
        evidence_ref = f"learning_evidence:candidate:{candidate_id}:decision:improved"
        session = self.store.record_session(
            curriculum_id=str(curriculum["curriculum_id"]),
            neuron_id=neuron_id,
            competency_id=str(competency["competency_id"]),
            state="lesson_prepared",
            material_refs=[str(candidate["source_ref"]), evidence_ref],
            independent_sources=1,
            lesson={
                "candidate_ids": [candidate_id],
                "content": str(candidate["content"]),
                "knowledge_type": self._candidate_type(candidate),
                "contract": contract.to_dict(),
                "router_version": ROUTER_VERSION,
            },
            exercise={
                "type": "causal_retrieval_and_application",
                "minimum_measured_runs": 5,
            },
            evaluation={
                "status": "post_run_measurement_pending",
                "evidence_ref": evidence_ref,
            },
            result="experimental",
            baseline_score=baseline,
        )
        assignment_id = f"nlearn-{uuid4().hex[:16]}"
        source_run_id = str(candidate["source_ref"] or "").removeprefix("run:")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO neuron_learning_assignments
                (assignment_id,candidate_id,neuron_id,session_id,source_run_id,knowledge_version,
                 status,decision,evidence_ref,pre_behavior_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,'experimental','authorized',?,?,?,?)""",
                (
                    assignment_id,
                    candidate_id,
                    neuron_id,
                    str(session["session_id"]),
                    source_run_id,
                    contract.current_knowledge_version + 1,
                    evidence_ref,
                    json.dumps(pre_behavior, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            event = conn.execute(
                "INSERT INTO neuron_education_events(session_id,neuron_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",
                (
                    str(session["session_id"]),
                    neuron_id,
                    "neural_knowledge_routed",
                    json.dumps(
                        {
                            "assignment_id": assignment_id,
                            "candidate_id": candidate_id,
                            "knowledge_version": contract.current_knowledge_version + 1,
                            "evidence_ref": evidence_ref,
                        },
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )
            if event.lastrowid is None:
                raise RuntimeError("neural_route_event_not_persisted")
            event_id = int(event.lastrowid)
        return {
            "status": "routed",
            "assignment_id": assignment_id,
            "candidate_id": candidate_id,
            "neuron_id": neuron_id,
            "neuron_name": str(neuron["name"]),
            "session_id": str(session["session_id"]),
            "knowledge_version": contract.current_knowledge_version + 1,
            "baseline_score": baseline,
            "evidence_ref": evidence_ref,
            "event_id": event_id,
            "contract": contract.to_dict(),
        }

    def record_rejection(self, candidate_id: str, reason: str) -> dict[str, Any]:
        """Registra una decisión negativa sin fabricar una asignación neuronal."""
        now = utc_now()
        with self._connect() as conn:
            event = conn.execute(
                """INSERT INTO neuron_education_events
                (session_id,neuron_id,event_type,payload_json,created_at)
                VALUES(NULL,NULL,'neural_knowledge_rejected',?,?)""",
                (
                    json.dumps(
                        {"candidate_id": candidate_id, "reason": reason},
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )
            if event.lastrowid is None:
                raise RuntimeError("neural_rejection_event_not_persisted")
            event_id = int(event.lastrowid)
        return {
            "event_id": event_id,
            "candidate_id": candidate_id,
            "reason": reason,
            "created_at": now,
        }

    def rejections(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id event_id,payload_json,created_at
                FROM neuron_education_events
                WHERE event_type='neural_knowledge_rejected'
                ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            payload = json.loads(str(row["payload_json"] or "{}"))
            result.append(
                {
                    "event_id": int(row["event_id"]),
                    "created_at": str(row["created_at"]),
                    **payload,
                }
            )
        return result

    def active_routes(
        self, candidate_ids: set[str] | None = None
    ) -> list[dict[str, Any]]:
        states = tuple(ACTIVE_ASSIGNMENT_STATES)
        marks = ",".join("?" for _ in states)
        params: list[Any] = list(states)
        filter_sql = ""
        if candidate_ids is not None:
            if not candidate_ids:
                return []
            filter_sql = (
                f" AND a.candidate_id IN ({','.join('?' for _ in candidate_ids)})"
            )
            params.extend(sorted(candidate_ids))
        with self._connect() as conn:
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='neurons'"
            ).fetchone():
                return []
            rows = conn.execute(
                f"""SELECT a.*,n.name neuron_name,n.mission,n.domain
                FROM neuron_learning_assignments a JOIN neurons n ON n.id=a.neuron_id
                WHERE a.status IN ({marks}){filter_sql}
                ORDER BY a.updated_at DESC""",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def has_learning_neurons(self) -> bool:
        """Indica si la base contiene destinos reales para el contrato opt-in."""
        with self._connect() as conn:
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='neurons'"
            ).fetchone():
                return False
            return bool(
                conn.execute(
                    "SELECT 1 FROM neurons WHERE status IN ('experimental','active','stable') LIMIT 1"
                ).fetchone()
            )

    def record_application(
        self,
        assignment_id: str,
        *,
        run_id: str,
        outcome_score: float,
        evidence_ref: str,
        routing_decision_id: str,
    ) -> dict[str, Any]:
        if not 0.0 <= outcome_score <= 1.0:
            raise ValueError("outcome_score fuera de rango")
        now = utc_now()
        with self._connect() as conn:
            assignment = conn.execute(
                "SELECT * FROM neuron_learning_assignments WHERE assignment_id=? AND status IN ('experimental','beneficial')",
                (assignment_id,),
            ).fetchone()
            if assignment is None:
                raise ValueError("assignment_not_active")
            before = conn.total_changes
            conn.execute(
                """INSERT OR IGNORE INTO neuron_education_applications
                (session_id,run_id,outcome_score,evidence_ref,created_at) VALUES(?,?,?,?,?)""",
                (
                    str(assignment["session_id"]),
                    run_id,
                    outcome_score,
                    evidence_ref,
                    now,
                ),
            )
            duplicate = conn.total_changes == before
            aggregate = conn.execute(
                "SELECT COUNT(*) uses,AVG(outcome_score) score FROM neuron_education_applications WHERE session_id=?",
                (str(assignment["session_id"]),),
            ).fetchone()
            uses = int(aggregate["uses"] or 0)
            score = float(aggregate["score"] or 0.0)
            conn.execute(
                """UPDATE neuron_learning_assignments SET use_count=?,outcome_score=?,
                post_behavior_json=?,updated_at=? WHERE assignment_id=?""",
                (
                    uses,
                    score,
                    json.dumps(
                        {
                            "run_id": run_id,
                            "routing_decision_id": routing_decision_id,
                            "evidence_ref": evidence_ref,
                            "score": outcome_score,
                        },
                        ensure_ascii=False,
                    ),
                    now,
                    assignment_id,
                ),
            )
            conn.execute(
                "INSERT INTO neuron_education_events(session_id,neuron_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",
                (
                    str(assignment["session_id"]),
                    int(assignment["neuron_id"]),
                    "neural_knowledge_applied",
                    json.dumps(
                        {
                            "assignment_id": assignment_id,
                            "candidate_id": str(assignment["candidate_id"]),
                            "run_id": run_id,
                            "routing_decision_id": routing_decision_id,
                            "outcome_score": outcome_score,
                            "evidence_ref": evidence_ref,
                            "duplicate": duplicate,
                        },
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )
        return {
            "assignment_id": assignment_id,
            "run_id": run_id,
            "uses": uses,
            "average_outcome_score": round(score, 4),
            "duplicate": duplicate,
        }

    def history(
        self, neuron_id: int | None = None, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if neuron_id is not None:
            where = "WHERE a.neuron_id=?"
            params.append(neuron_id)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT a.*,n.name neuron_name,n.mission,n.domain,
                q.title knowledge_title,q.content knowledge_content,
                q.source_ref knowledge_source_ref
                FROM neuron_learning_assignments a JOIN neurons n ON n.id=a.neuron_id
                JOIN learning_queue q ON q.candidate_id=a.candidate_id
                {where} ORDER BY a.updated_at DESC LIMIT ?""",
                params,
            ).fetchall()
            history: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                for field in ("pre_behavior_json", "post_behavior_json"):
                    item[field.removesuffix("_json")] = json.loads(
                        str(item.pop(field) or "{}")
                    )
                item["applications"] = [
                    dict(application)
                    for application in conn.execute(
                        """SELECT run_id,outcome_score,evidence_ref,created_at
                        FROM neuron_education_applications WHERE session_id=?
                        ORDER BY created_at""",
                        (str(row["session_id"]),),
                    )
                ]
                item["events"] = [
                    {
                        **dict(event),
                        "payload": json.loads(str(event["payload_json"] or "{}")),
                    }
                    for event in conn.execute(
                        """SELECT id event_id,event_type,payload_json,created_at
                        FROM neuron_education_events WHERE session_id=? ORDER BY id""",
                        (str(row["session_id"]),),
                    )
                ]
                for event in item["events"]:
                    event.pop("payload_json", None)
                history.append(item)
        return history

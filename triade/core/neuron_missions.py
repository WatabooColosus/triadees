"""Sistema de misiones neuronales — Tríade Ω.

Cada neurona activa tiene una misión que define qué investiga, de qué fuentes
puede aprender, qué acciones puede ejecutar y cómo se mide su progreso.

Ciclo de vida de una misión:
  candidate → experimental → stable → paused | rejected

Las misiones son persistentes en SQLite y auditables.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from triade.core.contracts import utc_now


# ── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class NeuronMission:
    neuron_id: int | None = None
    title: str = ""
    mission: str = ""
    domain: str = "general"
    allowed_sources: list[str] = field(default_factory=lambda: ["worker", "run", "federation"])
    allowed_actions: list[str] = field(default_factory=lambda: ["observe", "diagnose", "propose_learning"])
    schedule_hint: str = "every_cycle"
    status: str = "candidate"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    metrics: dict[str, Any] = field(default_factory=dict)
    id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["allowed_sources"] = self.allowed_sources
        d["allowed_actions"] = self.allowed_actions
        d["metrics"] = self.metrics
        return d


@dataclass(slots=True)
class NeuronWorkCycle:
    mission_id: int = 0
    neuron_id: int | None = None
    cycle_type: str = "observation"
    input_summary: str = ""
    output_summary: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    duration_ms: int = 0
    status: str = "completed"
    created_at: str = field(default_factory=utc_now)
    id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["evidence_refs"] = self.evidence_refs
        return d


@dataclass(slots=True)
class NeuronEvidence:
    mission_id: int = 0
    neuron_id: int | None = None
    evidence_type: str = "observation"
    source: str = "worker"
    content: str = ""
    refs: list[str] = field(default_factory=list)
    score: float = 0.0
    created_at: str = field(default_factory=utc_now)
    id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["refs"] = self.refs
        return d


@dataclass(slots=True)
class NeuronScore:
    mission_id: int = 0
    neuron_id: int | None = None
    score_type: str = "composite"
    value: float = 0.0
    components: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["components"] = self.components
        return d


# ── Store ────────────────────────────────────────────────────────────────────


class NeuronMissionStore:
    """Persistencia SQLite para misiones neuronales."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        schema_path = Path(__file__).resolve().parents[1] / "memory" / "schemas.sql"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(schema_path.read_text(encoding="utf-8"))

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Missions ────────────────────────────────────────────────────────

    def create_mission(self, mission: NeuronMission) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO neuron_missions
                (neuron_id, title, mission, domain, allowed_sources_json,
                 allowed_actions_json, schedule_hint, status, created_at, updated_at, metrics_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mission.neuron_id,
                    mission.title,
                    mission.mission,
                    mission.domain,
                    json.dumps(mission.allowed_sources, ensure_ascii=False),
                    json.dumps(mission.allowed_actions, ensure_ascii=False),
                    mission.schedule_hint,
                    mission.status,
                    mission.created_at,
                    mission.updated_at,
                    json.dumps(mission.metrics, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def get_mission(self, mission_id: int) -> NeuronMission | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM neuron_missions WHERE id = ?", (mission_id,)).fetchone()
        return self._mission_from_row(row) if row else None

    def get_missions_by_neuron(self, neuron_id: int) -> list[NeuronMission]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM neuron_missions WHERE neuron_id = ? ORDER BY updated_at DESC",
                (neuron_id,),
            ).fetchall()
        return [self._mission_from_row(r) for r in rows]

    def list_missions(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[NeuronMission]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM neuron_missions WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM neuron_missions ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._mission_from_row(r) for r in rows]

    def update_mission_status(self, mission_id: int, status: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE neuron_missions SET status = ?, updated_at = ? WHERE id = ?",
                (status, utc_now(), mission_id),
            )
            return cursor.rowcount > 0

    def update_mission_metrics(self, mission_id: int, metrics: dict[str, Any]) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE neuron_missions SET metrics_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(metrics, ensure_ascii=False), utc_now(), mission_id),
            )
            return cursor.rowcount > 0

    # ── Work Cycles ─────────────────────────────────────────────────────

    def record_cycle(self, cycle: NeuronWorkCycle) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO neuron_work_cycles
                (mission_id, neuron_id, cycle_type, input_summary, output_summary,
                 evidence_refs_json, duration_ms, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cycle.mission_id,
                    cycle.neuron_id,
                    cycle.cycle_type,
                    cycle.input_summary,
                    cycle.output_summary,
                    json.dumps(cycle.evidence_refs, ensure_ascii=False),
                    cycle.duration_ms,
                    cycle.status,
                    cycle.created_at,
                ),
            )
            return int(cursor.lastrowid)

    def list_cycles(self, mission_id: int, limit: int = 20) -> list[NeuronWorkCycle]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM neuron_work_cycles WHERE mission_id = ? ORDER BY id DESC LIMIT ?",
                (mission_id, limit),
            ).fetchall()
        return [self._cycle_from_row(r) for r in rows]

    # ── Evidence ────────────────────────────────────────────────────────

    def record_evidence(self, evidence: NeuronEvidence) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO neuron_evidence
                (mission_id, neuron_id, evidence_type, source, content, refs_json, score, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    evidence.mission_id,
                    evidence.neuron_id,
                    evidence.evidence_type,
                    evidence.source,
                    evidence.content,
                    json.dumps(evidence.refs, ensure_ascii=False),
                    evidence.score,
                    evidence.created_at,
                ),
            )
            return int(cursor.lastrowid)

    def list_evidence(self, mission_id: int, limit: int = 20) -> list[NeuronEvidence]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM neuron_evidence WHERE mission_id = ? ORDER BY id DESC LIMIT ?",
                (mission_id, limit),
            ).fetchall()
        return [self._evidence_from_row(r) for r in rows]

    # ── Scores ──────────────────────────────────────────────────────────

    def record_score(self, score: NeuronScore) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO neuron_scores
                (mission_id, neuron_id, score_type, value, components_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    score.mission_id,
                    score.neuron_id,
                    score.score_type,
                    score.value,
                    json.dumps(score.components, ensure_ascii=False),
                    score.created_at,
                ),
            )
            return int(cursor.lastrowid)

    def latest_score(self, mission_id: int) -> NeuronScore | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM neuron_scores WHERE mission_id = ? ORDER BY id DESC LIMIT 1",
                (mission_id,),
            ).fetchone()
        return self._score_from_row(row) if row else None

    # ── Helpers ─────────────────────────────────────────────────────────

    def _mission_from_row(self, row: sqlite3.Row) -> NeuronMission:
        d = dict(row)
        return NeuronMission(
            id=int(d["id"]),
            neuron_id=d.get("neuron_id"),
            title=str(d.get("title") or ""),
            mission=str(d.get("mission") or ""),
            domain=str(d.get("domain") or "general"),
            allowed_sources=json.loads(d.get("allowed_sources_json") or "[]"),
            allowed_actions=json.loads(d.get("allowed_actions_json") or "[]"),
            schedule_hint=str(d.get("schedule_hint") or "every_cycle"),
            status=str(d.get("status") or "candidate"),
            created_at=str(d.get("created_at") or ""),
            updated_at=str(d.get("updated_at") or ""),
            metrics=json.loads(d.get("metrics_json") or "{}"),
        )

    def _cycle_from_row(self, row: sqlite3.Row) -> NeuronWorkCycle:
        d = dict(row)
        return NeuronWorkCycle(
            id=int(d["id"]),
            mission_id=int(d["mission_id"]),
            neuron_id=d.get("neuron_id"),
            cycle_type=str(d.get("cycle_type") or "observation"),
            input_summary=str(d.get("input_summary") or ""),
            output_summary=str(d.get("output_summary") or ""),
            evidence_refs=json.loads(d.get("evidence_refs_json") or "[]"),
            duration_ms=int(d.get("duration_ms") or 0),
            status=str(d.get("status") or "completed"),
            created_at=str(d.get("created_at") or ""),
        )

    def _evidence_from_row(self, row: sqlite3.Row) -> NeuronEvidence:
        d = dict(row)
        return NeuronEvidence(
            id=int(d["id"]),
            mission_id=int(d["mission_id"]),
            neuron_id=d.get("neuron_id"),
            evidence_type=str(d.get("evidence_type") or "observation"),
            source=str(d.get("source") or "worker"),
            content=str(d.get("content") or ""),
            refs=json.loads(d.get("refs_json") or "[]"),
            score=float(d.get("score") or 0.0),
            created_at=str(d.get("created_at") or ""),
        )

    def _score_from_row(self, row: sqlite3.Row) -> NeuronScore:
        d = dict(row)
        return NeuronScore(
            id=int(d["id"]),
            mission_id=int(d["mission_id"]),
            neuron_id=d.get("neuron_id"),
            score_type=str(d.get("score_type") or "composite"),
            value=float(d.get("value") or 0.0),
            components=json.loads(d.get("components_json") or "{}"),
            created_at=str(d.get("created_at") or ""),
        )


def select_relevant_missions(
    missions: list[NeuronMission],
    user_input: str = "",
    domain: str = "",
    memory_context: dict[str, Any] | None = None,
    limit: int = 5,
) -> list[NeuronMission]:
    """Selecciona misiones relevantes por dominio, triggers y estado.

    Criterios:
    - mission.status in {"candidate", "experimental", "stable"}
    - domain coincide si se proporciona
    - triggers/rules si existen y coinciden con user_input
    - prioridad por score reciente o updated_at
    """
    user_lower = user_input.lower()
    active_statuses = {"candidate", "experimental", "stable"}
    scored: list[tuple[float, NeuronMission]] = []

    for m in missions:
        if m.status not in active_statuses:
            continue

        score = 0.0

        if domain and m.domain == domain:
            score += 2.0

        if user_lower:
            mission_lower = m.mission.lower()
            title_lower = m.title.lower()
            if any(word in mission_lower or word in title_lower for word in user_lower.split() if len(word) > 3):
                score += 1.0

        if m.metrics:
            recent_score = m.metrics.get("composite_score") or m.metrics.get("score")
            if recent_score is not None:
                score += float(recent_score)

        if score > 0:
            scored.append((score, m))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:limit]]

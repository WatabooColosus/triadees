"""Mission Planner — planificador inteligente de tareas neuronales.

Lee el estado real del sistema y produce una lista priorizada de WorkerTask
con razones explicadas. Reemplaza el enqueue_defaults ciego del scheduler.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now
from triade.core.error_bus import record_internal_error
from triade.core.neuron_missions import NeuronMissionStore, NeuronMission


@dataclass(slots=True)
class PlannedTask:
    task_type: str
    priority: int = 50
    reason: str = ""
    source: str = "mission_planner"
    planner_score: float = 0.0
    related_neuron_id: int | None = None
    related_candidate_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "priority": self.priority,
            "reason": self.reason,
            "source": self.source,
            "planner_score": self.planner_score,
            "related_neuron_id": self.related_neuron_id,
            "related_candidate_id": self.related_candidate_id,
            "payload": self.payload,
        }


class MissionPlanner:
    """Planifica tareas basándose en el estado real del sistema."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def plan_cycle(self, run_ref: str | None = None) -> list[PlannedTask]:
        """Produce una lista priorizada de tareas para el próximo ciclo."""
        tasks: list[PlannedTask] = []

        tasks.extend(self._plan_baseline())
        tasks.extend(self._plan_pending_learning())
        tasks.extend(self._plan_failed_recent())
        tasks.extend(self._plan_memory_consolidation())
        tasks.extend(self._plan_active_missions())
        tasks.extend(self._plan_federation_inbox())
        tasks.extend(self._plan_system_debt())
        tasks.extend(self._plan_neuron_formation())

        tasks.sort(key=lambda t: t.priority)

        if len(tasks) > 15:
            tasks = tasks[:15]

        return tasks

    def _plan_baseline(self) -> list[PlannedTask]:
        """Tareas base condicionales al estado real del sistema.

        - pulse_check: siempre
        - pending_learning_review: solo si hay candidates/evaluated/verified
        - semantic_memory_governance: solo si hay documentos o actividad reciente
        - neuron_autopromotion: solo si hay scores/evidencia suficiente
        """
        tasks: list[PlannedTask] = []

        # pulse_check siempre se ejecuta
        tasks.append(PlannedTask(
            task_type="pulse_check",
            priority=10,
            reason="Verificación base de pulso del sistema",
            source="mission_planner_baseline",
            planner_score=1.0,
        ))

        try:
            with self._connect() as conn:
                # pending_learning_review: solo si hay work que hacer
                lr = conn.execute(
                    """SELECT COUNT(*) as cnt FROM learning_queue
                    WHERE status IN ('candidate', 'evaluated', 'verified')"""
                ).fetchone()
                lr_cnt = int(lr["cnt"] or 0) if lr else 0
                if lr_cnt > 0:
                    tasks.append(PlannedTask(
                        task_type="pending_learning_review",
                        priority=12,
                        reason=f"{lr_cnt} candidatos en pipeline de aprendizaje (candidate/evaluated/verified)",
                        source="mission_planner_baseline",
                        planner_score=min(1.0, 0.5 + lr_cnt / 20),
                    ))

                # semantic_memory_governance: solo si hay documentos o actividad
                sm = conn.execute(
                    """SELECT COUNT(*) as cnt FROM semantic_memory
                    WHERE status IN ('candidate', 'experimental')
                    OR updated_at > datetime('now', '-6 hours')"""
                ).fetchone()
                sm_cnt = int(sm["cnt"] or 0) if sm else 0
                if sm_cnt > 0:
                    tasks.append(PlannedTask(
                        task_type="semantic_memory_governance",
                        priority=13,
                        reason=f"{sm_cnt} documentos semánticos candidate/experimental",
                        source="mission_planner_baseline",
                        planner_score=min(1.0, 0.5 + sm_cnt / 20),
                    ))

                # neuron_autopromotion: solo si hay evidencia suficiente
                ns = conn.execute(
                    """SELECT COUNT(DISTINCT n.id) as cnt
                    FROM neurons n
                    LEFT JOIN neuron_training nt ON nt.neuron_id = n.id
                    LEFT JOIN neuron_activity na ON na.neuron_id = n.id
                    WHERE n.status IN ('experimental', 'candidate', 'candidate_reviewable')
                    AND (nt.score >= 0.65 OR na.id IS NOT NULL)"""
                ).fetchone()
                ns_cnt = int(ns["cnt"] or 0) if ns else 0
                if ns_cnt > 0:
                    tasks.append(PlannedTask(
                        task_type="neuron_autopromotion",
                        priority=15,
                        reason=f"{ns_cnt} neuronas promovibles con training o evidencia",
                        source="mission_planner_baseline",
                        planner_score=min(1.0, 0.55 + ns_cnt / 20),
                    ))
        except Exception as exc:
            record_internal_error(
                "mission_planner.baseline",
                exc,
                payload={"module": __name__, "function": "_plan_baseline", "operation": "baseline_sql_queries"},
                db_path=self.db_path,
            )

        return tasks

    def _plan_pending_learning(self) -> list[PlannedTask]:
        """Encola revisión de candidatos de aprendizaje pendientes."""
        tasks: list[PlannedTask] = []
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """SELECT id, title, source_type, risk_level, confidence, status
                    FROM learning_queue
                    WHERE status IN ('candidate', 'evaluated')
                    ORDER BY confidence DESC, id ASC
                    LIMIT 5"""
                ).fetchall()
            for row in rows:
                confidence = float(row["confidence"] or 0)
                priority = 20 if confidence >= 0.7 else 30
                tasks.append(PlannedTask(
                    task_type="pending_learning_review",
                    priority=priority,
                    reason=f"Candidato de aprendizaje '{(row['title'] or '')[:40]}' "
                           f"status={row['status']} confidence={confidence:.2f}",
                    source="mission_planner",
                    planner_score=max(0.1, min(1.0, confidence)),
                    related_candidate_id=int(row["id"]),
                    payload={"candidate_id": int(row["id"]), "source_type": row["source_type"]},
                ))
        except Exception as exc:
            record_internal_error(
                "mission_planner.pending_learning",
                exc,
                payload={"module": __name__, "function": "_plan_pending_learning", "operation": "select_learning_queue"},
                db_path=self.db_path,
            )
        return tasks

    def _plan_failed_recent(self) -> list[PlannedTask]:
        """Reintenta tareas fallidas recientes (una vez)."""
        tasks: list[PlannedTask] = []
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """SELECT id, task_type, error, payload_json
                    FROM worker_tasks
                    WHERE status = 'failed'
                    AND finished_at > datetime('now', '-1 hour')
                    ORDER BY id DESC LIMIT 3"""
                ).fetchall()
            for row in rows:
                payload = json.loads(row["payload_json"] or "{}")
                if payload.get("retried"):
                    continue
                tasks.append(PlannedTask(
                    task_type=str(row["task_type"]),
                    priority=40,
                    reason=f"Reintento de tarea fallida: {row['task_type']} error={(row['error'] or '')[:60]}",
                    source="mission_planner_retry",
                    planner_score=0.55,
                    payload={**payload, "retried": True, "original_task_id": int(row["id"])},
                ))
        except Exception as exc:
            record_internal_error(
                "mission_planner.failed_recent",
                exc,
                payload={"module": __name__, "function": "_plan_failed_recent", "operation": "select_failed_worker_tasks"},
                db_path=self.db_path,
            )
        return tasks

    def _plan_memory_consolidation(self) -> list[PlannedTask]:
        """Programa consolidación de memoria verificada pendiente."""
        tasks: list[PlannedTask] = []
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """SELECT COUNT(*) as cnt FROM learning_queue
                    WHERE status = 'verified'"""
                ).fetchone()
                cnt = int(row["cnt"] or 0) if row else 0
            if cnt > 0:
                tasks.append(PlannedTask(
                    task_type="memory_consolidation_review",
                    priority=35,
                    reason=f"{cnt} candidatos verified pendientes de consolidar",
                    source="mission_planner",
                    planner_score=min(1.0, 0.5 + cnt / 10),
                    payload={"pending_count": cnt},
                ))
        except Exception as exc:
            record_internal_error(
                "mission_planner.memory_consolidation",
                exc,
                payload={"module": __name__, "function": "_plan_memory_consolidation", "operation": "count_verified_learning"},
                db_path=self.db_path,
            )
        return tasks

    def _plan_active_missions(self) -> list[PlannedTask]:
        """Programa ciclos de trabajo para misiones neuronales activas."""
        tasks: list[PlannedTask] = []
        try:
            store = NeuronMissionStore(db_path=self.db_path)
            missions = store.list_missions(status="experimental", limit=5)
            missions.extend(store.list_missions(status="stable", limit=5))
            for m in missions:
                tasks.append(PlannedTask(
                    task_type="experimental_neuron_activity",
                    priority=25,
                    reason=f"Misión activa '{m.title}' dominio={m.domain}",
                    source="mission_planner_mission",
                    planner_score=0.8,
                    related_neuron_id=m.neuron_id,
                    payload={
                        "mission_id": m.id,
                        "neuron_id": m.neuron_id,
                        "domain": m.domain,
                        "allowed_sources": m.allowed_sources,
                        "allowed_actions": m.allowed_actions,
                    },
                ))
        except Exception as exc:
            record_internal_error(
                "mission_planner.active_missions",
                exc,
                payload={"module": __name__, "function": "_plan_active_missions", "operation": "list_experimental_missions"},
                db_path=self.db_path,
            )
        return tasks

    def _plan_federation_inbox(self) -> list[PlannedTask]:
        """Revisa inbox de federación si hay nodos con mensajes."""
        tasks: list[PlannedTask] = []
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """SELECT COUNT(*) as cnt FROM federated_exchange_log
                    WHERE decision = 'pending'
                    AND created_at > datetime('now', '-1 hour')"""
                ).fetchone()
                cnt = int(row["cnt"] or 0) if row else 0
            if cnt > 0:
                tasks.append(PlannedTask(
                    task_type="federation_inbox_review",
                    priority=30,
                    reason=f"{cnt} mensajes federados pendientes",
                    source="mission_planner",
                    planner_score=min(1.0, 0.5 + cnt / 10),
                    payload={"pending_count": cnt},
                ))
        except Exception as exc:
            record_internal_error(
                "mission_planner.federation_inbox",
                exc,
                payload={"module": __name__, "function": "_plan_federation_inbox", "operation": "count_pending_federation"},
                db_path=self.db_path,
            )
        return tasks

    def _plan_system_debt(self) -> list[PlannedTask]:
        """Detecta deuda del sistema que puede generar candidatos."""
        tasks: list[PlannedTask] = []
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(*) as cnt FROM runs WHERE status = 'ok'").fetchone()
                runs_ok = int(row["cnt"] or 0) if row else 0
                row2 = conn.execute("SELECT COUNT(*) as cnt FROM episodic_memory").fetchone()
                episodes = int(row2["cnt"] or 0) if row2 else 0
            if runs_ok > 5 and episodes < runs_ok * 2:
                tasks.append(PlannedTask(
                    task_type="system_debt_scan",
                    priority=45,
                    reason=f"Deuda detectada: {runs_ok} runs pero solo {episodes} episodios",
                    source="mission_planner",
                    planner_score=min(1.0, (runs_ok - episodes) / max(1, runs_ok)),
                    payload={"runs_ok": runs_ok, "episodes": episodes},
                ))
        except Exception as exc:
            record_internal_error(
                "mission_planner.system_debt",
                exc,
                payload={"module": __name__, "function": "_plan_system_debt", "operation": "count_runs_and_episodes"},
                db_path=self.db_path,
            )
        return tasks

    def _plan_neuron_formation(self) -> list[PlannedTask]:
        """Evalúa si hay candidatos neuronales sin training."""
        tasks: list[PlannedTask] = []
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """SELECT COUNT(*) as cnt FROM neurons
                    WHERE status IN ('candidate', 'candidate_reviewable')"""
                ).fetchone()
                cnt = int(row["cnt"] or 0) if row else 0
            if cnt > 0:
                tasks.append(PlannedTask(
                    task_type="neuron_candidate_formation",
                    priority=28,
                    reason=f"{cnt} candidatos neuronales pendientes de evaluación",
                    source="mission_planner",
                    planner_score=min(1.0, 0.5 + cnt / 10),
                    payload={"pending_candidates": cnt},
                ))
        except Exception as exc:
            record_internal_error(
                "mission_planner.neuron_formation",
                exc,
                payload={"module": __name__, "function": "_plan_neuron_formation", "operation": "count_candidate_neurons"},
                db_path=self.db_path,
            )
        return tasks

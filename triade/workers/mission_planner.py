"""Mission Planner — planificador inteligente de tareas neuronales.

Lee el estado real del sistema y produce una lista priorizada de WorkerTask
con razones explicadas. Reemplaza el enqueue_defaults ciego del scheduler.
"""

from __future__ import annotations

import json
import os
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from triade.core.error_bus import record_internal_error
from triade.core.neuron_missions import NeuronMissionStore
from triade.db import sqlite3
from triade.learning.knowledge_probe import extract_target
from triade.learning.pipeline import LearningPipeline
from triade.neurons.education_resolver import MIN_APPLIED_RUNS
from triade.self_improvement.auto_approval import auto_approvable_open_proposals

MISSION_PLANNER_ERRORS = (
    sqlite3.Error,
    OSError,
    ImportError,
    sqlite3.Error,
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
)


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

    #: Cuántos candidatos se miran por ciclo buscando uno medible. Se recorre en
    #: memoria una tanda ya ordenada, no los 665: si en los 200 más recientes no
    #: hay ninguno con un dato comprobable, el problema es la cosecha de
    #: candidatos y no la selección.
    EVIDENCE_SCAN_LIMIT = 200

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
        tasks.extend(self._plan_neural_learning_distribution())
        tasks.extend(self._plan_active_missions())
        tasks.extend(self._plan_federation_inbox())
        tasks.extend(self._plan_system_debt())
        tasks.extend(self._plan_neuron_formation())
        tasks.extend(self._plan_research_curriculum())
        tasks.extend(self._plan_neuron_education())
        tasks.extend(self._plan_self_improvement())
        tasks.extend(self._plan_canary_observation())
        tasks.extend(self._plan_peft_canary_observation())
        # La condición miraba sólo `TRIADE_BACKUP_KEY`, y `encrypted_backup.py`
        # acepta además `TRIADE_BACKUP_KEY_FILE`: con la clave en fichero, la
        # tarea no se planificaba aunque el backup fuese perfectamente posible.
        #
        # Y sin ninguna de las dos no pasaba nada: ni tarea, ni aviso, ni rastro.
        # El 2026-07-31 la clave dejó de estar en el entorno y el sistema pasó
        # cuatro días sin un solo backup sin que nada lo dijera. Un backup que
        # deja de hacerse en silencio es peor que no tenerlo, porque nadie va a
        # buscarlo hasta que haga falta. Ahora la falta se registra como error
        # interno, que es una superficie que ya se lee.
        # Prioridad 4, por delante del aprendizaje continuo. Estaba en 80 —la más
        # baja de todo el planificador— y con la cola ordenando por
        # `prioridad - minutos_de_espera`, competía contra tareas de 5 a 15 que se
        # recrean sin parar: medido el 2026-08-07, la tarea encolada a las 22:22
        # seguía en `pending` con `attempt=0` una hora después, y necesitaba unos
        # 74 minutos de espera sólo para ponerse la primera.
        #
        # No es una preferencia: es la única categoría cuyo fallo es
        # irrecuperable. Una consolidación de aprendizaje que se retrasa una hora
        # se hace después; una copia que no se hizo no se puede hacer después.
        #
        # Adelantarla no la vuelve voraz: `AdaptiveScheduler` no la replanifica
        # antes de media hora (`get_recommended_interval` = 3600 s, se salta si
        # `elapsed < interval * 0.5`) y el dedup por `(task_type, payload_hash)`
        # impide una segunda mientras haya una activa. Cuesta ~11 s medidos.
        if os.getenv("TRIADE_BACKUP_KEY") or os.getenv("TRIADE_BACKUP_KEY_FILE"):
            tasks.append(
                PlannedTask(
                    task_type="encrypted_backup",
                    priority=4,
                    reason="Backup diario cifrado y restaurable",
                    source="backup_retention_policy",
                    planner_score=0.4,
                )
            )
        else:
            record_internal_error(
                "mission_planner.backup_key_missing",
                RuntimeError(
                    "sin TRIADE_BACKUP_KEY ni TRIADE_BACKUP_KEY_FILE: "
                    "no se planifica ningún backup y la base queda sin copia"
                ),
                payload={"module": __name__, "function": "plan_cycle"},
                db_path=self.db_path,
            )

        tasks.sort(key=lambda t: t.priority)
        deduplicated: list[PlannedTask] = []
        seen: set[tuple[str, int | None, int | None, str]] = set()
        for task in tasks:
            key = (
                task.task_type,
                task.related_neuron_id,
                task.related_candidate_id,
                str(task.payload.get("goal_id") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(task)
        tasks = deduplicated

        if len(tasks) > 15:
            tasks = tasks[:15]

        return tasks

    def _plan_neural_learning_distribution(self) -> list[PlannedTask]:
        """Distribuye un consolidado todavía no asignado a ninguna neurona."""
        try:
            # Inicializar el router aplica la migración canónica antes de leer.
            from triade.neurons.learning_router import (
                ROUTER_VERSION,
                NeuralLearningRouter,
            )

            NeuralLearningRouter(self.db_path)
            with closing(self._connect()) as conn, conn:
                row = conn.execute(
                    # `evidence_verified` entra aquí junto a `consolidated`
                    # porque pedir sólo lo consolidado cerraba el círculo: ver
                    # `ROUTABLE_STATES` en `learning_router.py`. Sin esto el
                    # planner no encolaba destino para nada aprendido después
                    # del 2026-08-11 y la inyección se quedaba a cero.
                    """SELECT q.candidate_id FROM learning_queue q
                    WHERE q.status IN ('evidence_verified','consolidated')
                      AND COALESCE(q.risk_level,'low') IN ('none','low','medium')
                      AND EXISTS (
                        SELECT 1 FROM learning_evidence e
                        WHERE e.candidate_id=q.candidate_id AND e.decision='improved'
                      )
                      AND NOT EXISTS (
                        SELECT 1 FROM neuron_learning_assignments a
                        WHERE a.candidate_id=q.candidate_id
                      )
                      -- Un rechazo no escribe asignación, así que sin esta
                      -- cláusula el `NOT EXISTS` de arriba sigue siendo cierto
                      -- y el mismo candidato vuelve a salir elegido cada ciclo:
                      -- 25 rechazos idénticos de `dst-a705dd2c47a368e1` por
                      -- `no_compatible_neuron` en once minutos, medidos el
                      -- 2026-08-27. Es la tercera vez que aparece este patrón
                      -- —antes en `learning_evidence_generation` (F-037) y en
                      -- `learning_distillation_attempts`—: quien decide que no
                      -- tiene que dejarlo escrito, o no ha decidido nada.
                      AND NOT EXISTS (
                        SELECT 1 FROM neuron_education_events ev
                        WHERE ev.event_type='neural_knowledge_rejected'
                          AND json_extract(ev.payload_json,'$.candidate_id')
                              = q.candidate_id
                          AND json_extract(ev.payload_json,'$.router_version')
                              = ?
                      )
                    ORDER BY q.updated_at LIMIT 1""",
                    (ROUTER_VERSION,),
                ).fetchone()
            if row is None:
                return []
            candidate_id = str(row["candidate_id"])
            return [
                PlannedTask(
                    task_type="neural_learning_distribution",
                    priority=24,
                    reason=f"conocimiento consolidado {candidate_id} sin destino neuronal",
                    source="governed_neural_learning",
                    planner_score=0.85,
                    payload={"candidate_id": candidate_id},
                )
            ]
        except MISSION_PLANNER_ERRORS as exc:
            record_internal_error(
                "mission_planner.neural_learning_distribution",
                exc,
                db_path=self.db_path,
            )
            return []

    def _plan_research_curriculum(self) -> list[PlannedTask]:
        try:
            with closing(self._connect()) as conn, conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM neurons WHERE status IN ('experimental','candidate','candidate_reviewable')"
                ).fetchone()
            count = int(row["cnt"] or 0) if row else 0
            if count:
                return [
                    PlannedTask(
                        task_type="research_curriculum",
                        priority=45,
                        reason=f"Currículo dirigido por {count} lagunas neuronales reales",
                        source="neural_gap_curriculum",
                        planner_score=0.65,
                    )
                ]
        except MISSION_PLANNER_ERRORS as exc:
            record_internal_error(
                "mission_planner.research_curriculum", exc, db_path=self.db_path
            )
        return []

    def _plan_self_improvement(self) -> list[PlannedTask]:
        """Agenda el ciclo de automejora si hay algo que evaluar.

        «Algo que evaluar» son dos casos, y hasta el 2026-08-11 sólo se miraba
        el primero:

        1. una propuesta ya `approved` —por una persona o por la política—;
        2. una propuesta `open` que la política **puede** aprobar ahora.

        Faltar el segundo dejaba el circuito muerto. La aprobación por política
        vive dentro de `_self_improvement_evaluation`, así que exigir `approved`
        para encolar esa misma tarea era pedirle a la cadena que empezara por el
        segundo eslabón: una propuesta abierta no podía llegar a aprobada por sí
        sola, y todo lo que cuelga de ahí —candidatos, canarios, observaciones—
        se quedaba a cero para siempre.

        Lo que no se hace, y es deliberado: encolar porque exista una propuesta
        abierta *cualquiera*. Si la política no va a poder aprobarla —umbral,
        firma humana exigida—, la tarea no tendría nada que hacer y el bucle
        giraría en vacío, que es el fallo contrario. Por eso se pregunta si es
        auto-aprobable, no si existe.
        """
        try:
            with closing(self._connect()) as conn, conn:
                table = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='improvement_proposals'"
                ).fetchone()
                if not table:
                    return []
                row = conn.execute(
                    "SELECT COUNT(*) cnt FROM improvement_proposals "
                    "WHERE status = 'approved'"
                ).fetchone()
                approved = int(row["cnt"] or 0) if row else 0
                approvable = (
                    auto_approvable_open_proposals(conn) if not approved else []
                )
            if approved:
                return [
                    PlannedTask(
                        task_type="self_improvement_evaluation",
                        priority=38,
                        reason=f"{approved} propuesta(s) aprobada(s) esperando verificación",
                        source="human_approved_improvement",
                        planner_score=0.65,
                    )
                ]
            if approvable:
                return [
                    PlannedTask(
                        task_type="self_improvement_evaluation",
                        priority=38,
                        reason=(
                            f"{len(approvable)} propuesta(s) abierta(s) por encima del "
                            "umbral de aprobación por política"
                        ),
                        source="policy_approvable_improvement",
                        planner_score=0.65,
                        payload={"proposal_ids": approvable[:5]},
                    )
                ]
        except MISSION_PLANNER_ERRORS as exc:
            record_internal_error(
                "mission_planner.self_improvement", exc, db_path=self.db_path
            )
        return []

    def _plan_canary_observation(self) -> list[PlannedTask]:
        """Observa el canary abierto, si lo hay.

        `self_improvement_canary_observation` tenía handler completo, política de
        concurrencia y clave de exclusión, y **ningún productor en todo el
        repositorio**. Un canary se abría en `canary_running` y no se observaba
        jamás: ni graduaba, ni se revertía, ni acumulaba observaciones.

        El productor va aquí y no dentro de la evaluación por lo que dice el
        propio handler: esperar dentro de `run_once()` a que ocurran suficientes
        conversaciones significaría sostener un lease durante horas. Cada ciclo
        aporta lo que haya y se va.
        """
        try:
            with closing(self._connect()) as conn, conn:
                if not conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='improvement_canaries'"
                ).fetchone():
                    return []
                fila = conn.execute(
                    "SELECT canary_id, candidate_id FROM improvement_canaries "
                    "WHERE status = 'running' ORDER BY created_at LIMIT 1"
                ).fetchone()
            if fila is None:
                return []
            candidate_id = str(fila["candidate_id"] or "")
            return [
                PlannedTask(
                    task_type="self_improvement_canary_observation",
                    priority=36,
                    reason=(
                        f"canary {fila['canary_id']} abierto: acumular "
                        "observaciones para decidir graduación o rollback"
                    ),
                    source="open_canary",
                    planner_score=0.6,
                    payload={
                        "candidate_id": candidate_id,
                        "canary_id": str(fila["canary_id"] or ""),
                    },
                )
            ]
        except MISSION_PLANNER_ERRORS as exc:
            record_internal_error(
                "mission_planner.canary_observation", exc, db_path=self.db_path
            )
        return []

    def _plan_neuron_education(self) -> list[PlannedTask]:
        """Educa solo neuronas experimentales con revisión vencida o sin competencia."""
        try:
            with closing(self._connect()) as conn, conn:
                tables = {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if "neuron_competencies" in tables:
                    row = conn.execute(
                        """SELECT COUNT(*) cnt FROM neurons n
                        LEFT JOIN neuron_competencies c ON c.neuron_id=n.id AND c.domain=n.domain
                        WHERE n.status='experimental' AND (c.next_review IS NULL OR datetime(c.next_review)<=datetime('now'))"""
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT COUNT(*) cnt FROM neurons WHERE status='experimental'"
                    ).fetchone()
                due_neurons = int(row["cnt"] or 0) if row else 0
                resolvable_sessions = 0
                if {
                    "neuron_education_sessions",
                    "neuron_education_applications",
                }.issubset(tables):
                    ready = conn.execute(
                        """SELECT COUNT(*) cnt
                        FROM neuron_education_sessions s
                        WHERE s.state='lesson_prepared'
                          AND s.baseline_score IS NOT NULL
                          AND (SELECT COUNT(*)
                               FROM neuron_education_applications a
                               WHERE a.session_id=s.session_id) >= ?""",
                        (MIN_APPLIED_RUNS,),
                    ).fetchone()
                    resolvable_sessions = int(ready["cnt"] or 0) if ready else 0
            if due_neurons or resolvable_sessions:
                reasons = []
                if due_neurons:
                    reasons.append(
                        f"{due_neurons} neuronas experimentales requieren educación o revisión"
                    )
                if resolvable_sessions:
                    reasons.append(
                        f"{resolvable_sessions} sesiones tienen {MIN_APPLIED_RUNS}+ runs medidos y requieren resolución"
                    )
                return [
                    PlannedTask(
                        task_type="neuron_education_cycle",
                        # 42 la dejaba siempre por detrás de `research_curriculum`
                        # (45), y no por prioridad sino por edad: `claim()` ordena
                        # por `priority − MIN(100, edad_en_minutos)`, la de
                        # investigación se encola antes y envejece antes, así que
                        # gana el hueco cada vez. Medido el 2026-08-09: en 72
                        # minutos de autonomía, `research_curriculum` se ejecutó
                        # dos veces y esta **ninguna**. El sistema investigaba y
                        # no estudiaba nunca lo investigado: 4 candidatos
                        # acumulados y 0 lecciones.
                        #
                        # 20 no la pone por delante de la observación barata
                        # (`bodega_global_review` 12, `semantic_memory_governance`
                        # 13): la pone a competir de verdad en vez de esperar a
                        # una ventana vacía. No toca ninguna puerta de gobierno —
                        # el ciclo sigue exigiendo dos fuentes independientes y
                        # cinco runs medidos para decidir algo.
                        priority=20,
                        reason="; ".join(reasons),
                        source="governed_neuron_education",
                        planner_score=0.7,
                        # Resolver una lección que ya alcanzó el mínimo de usos es
                        # consecuencia de un evento, no mantenimiento periódico.
                        # No debe esperar el intervalo adaptativo del ciclo.
                        payload={"resolution_ready": bool(resolvable_sessions)},
                    )
                ]
        except MISSION_PLANNER_ERRORS as exc:
            record_internal_error(
                "mission_planner.neuron_education", exc, db_path=self.db_path
            )
        return []

    def _plan_baseline(self) -> list[PlannedTask]:
        """Tareas base condicionales al estado real del sistema.

        - pulse_check: siempre
        - pending_learning_review: solo si hay candidates/evaluated/verified
        - semantic_memory_governance: solo si hay documentos o actividad reciente
        - neuron_autopromotion: solo si hay scores/evidencia suficiente
        """
        tasks: list[PlannedTask] = []

        # `bodega_global_review` no lo producía nadie. Todo lo demás sobre él ya
        # estaba declarado: handler en `worker_loop`, política de concurrencia,
        # `TASK_PRODUCERS` diciendo «MissionPlanner», y —lo que lo decide— una
        # cadencia de 180 s en `AdaptiveScheduler.DEFAULT_INTERVALS`, el mismo
        # escalón que `semantic_memory_governance`. Los tipos bajo demanda llevan
        # ahí `0.0`; éste no. El contrato dice periódico.
        #
        # Su única vía de encolado era `enqueue_defaults()`, que es el *fallback*
        # de `schedule_cycle` y sólo corre si `plan_cycle()` devuelve vacío, cosa
        # que nunca hace: el productor existía en el código y el runtime no lo
        # alcanzaba jamás.
        #
        # Va condicionado a que haya memoria que revisar, no incondicional: en
        # este planificador `pulse_check` es la única tarea que se emite siempre
        # —es el signo vital—, y todo lo demás sólo se planifica si hay trabajo.
        # Una Tríade recién nacida planifica su pulso y nada más, y esa es una
        # propiedad que conviene conservar. `should_skip_task` respeta además los
        # 180 s, así que no se encola en cada ciclo.
        #
        # Prioridad 12: por detrás del pulso vital, cuya cadencia es seis veces
        # más rápida. Es una revisión de solo lectura —no consolida memoria ni
        # toca `identity_core`—.
        # pulse_check siempre se ejecuta
        tasks.append(
            PlannedTask(
                task_type="pulse_check",
                priority=10,
                reason="Verificación base de pulso del sistema",
                source="mission_planner_baseline",
                planner_score=1.0,
            )
        )

        try:
            with closing(self._connect()) as conn, conn:
                episodios = conn.execute(
                    "SELECT COUNT(*) as cnt FROM episodic_memory"
                ).fetchone()
                episodios_cnt = int(episodios["cnt"] or 0) if episodios else 0
                if episodios_cnt > 0:
                    tasks.append(
                        PlannedTask(
                            task_type="bodega_global_review",
                            priority=12,
                            reason=(
                                f"Revisión de memoria sobre {episodios_cnt} "
                                "episodios, learning_queue y stable_audit"
                            ),
                            source="mission_planner_baseline",
                            planner_score=0.8,
                        )
                    )

                # pending_learning_review: solo si hay work que hacer
                lr = conn.execute(
                    """SELECT COUNT(*) as cnt FROM learning_queue
                    WHERE status IN ('candidate', 'evaluated')"""
                ).fetchone()
                lr_cnt = int(lr["cnt"] or 0) if lr else 0
                if lr_cnt > 0:
                    tasks.append(
                        PlannedTask(
                            task_type="pending_learning_review",
                            priority=5,
                            reason=f"{lr_cnt} candidatos con transición ejecutable (candidate/evaluated)",
                            source="mission_planner_baseline",
                            planner_score=min(1.0, 0.5 + lr_cnt / 20),
                        )
                    )

                # learning_candidate_deduplication: sólo si ha entrado material
                # que `analyze()` todavía no haya examinado.
                #
                # Aquí vivía la condición «candidatos sin fila en
                # `learning_candidate_groups`», y era insatisfacible por
                # construcción: `analyze()` descarta todo grupo de un solo
                # miembro (`len(grupo) < 2`), así que un candidato único nunca
                # recibe fila y cuenta como «sin agrupar» para siempre. El
                # 2026-08-27 eran 612 de 1.040, y la tarea llevaba 8.448
                # ejecuciones desde el 1-ago sin escribir una sola fila: los 428
                # duplicados reales ya estaban guardados y `apply()` es
                # idempotente. Cada pasada gastaba ranura de obrero y
                # presupuesto de CPU del gobernador, que es el mismo que frena
                # la cadena de aprendizaje: el no-op no era gratis, competía.
                #
                # Lo que decide si hay trabajo no es quién quedó agrupado, sino
                # si hay material nuevo desde el último examen. La marca de agua
                # es la fecha en que se **programó** el último dedup completado,
                # no la de su fin: un candidato que entra mientras la tarea
                # corre puede no haber sido leído, y equivocarse hacia una
                # pasada de más es recuperable — hacia una de menos, no.
                try:
                    sin_examinar = conn.execute(
                        """SELECT COUNT(*) AS cnt FROM learning_queue q
                        WHERE q.created_at > COALESCE(
                            (SELECT MAX(t.created_at) FROM autonomous_tasks t
                              WHERE t.task_type = 'learning_candidate_deduplication'
                                AND t.status = 'completed'), '')"""
                    ).fetchone()
                    sin_examinar_cnt = (
                        int(sin_examinar["cnt"] or 0) if sin_examinar else 0
                    )
                except sqlite3.Error:
                    # Sin cola de tareas todavía no se ha examinado nada, así
                    # que está sin examinar **todo lo que haya** — que en una
                    # base recién creada es cero. Poner un 1 de respaldo, como
                    # se hacía antes, planificaba una deduplicación sobre una
                    # cola vacía: trabajo garantizado sin nada que agrupar.
                    try:
                        pendiente = conn.execute(
                            "SELECT COUNT(*) AS cnt FROM learning_queue"
                        ).fetchone()
                        sin_examinar_cnt = (
                            int(pendiente["cnt"] or 0) if pendiente else 0
                        )
                    except sqlite3.Error:
                        sin_examinar_cnt = 0
                if sin_examinar_cnt > 0:
                    tasks.append(
                        PlannedTask(
                            task_type="learning_candidate_deduplication",
                            priority=6,
                            reason=(
                                f"{sin_examinar_cnt} candidatos sin examinar "
                                "desde el último dedup"
                            ),
                            source="mission_planner_baseline",
                            planner_score=min(1.0, 0.4 + sin_examinar_cnt / 200),
                        )
                    )

                # learning_claim_distillation: sólo si hay padres `web` sin
                # hijo destilado y **sin intento previo**. La segunda condición
                # es la que de verdad frena: de 46 padres `web` reales sólo 6
                # dan aserción, y sin mirar `learning_distillation_attempts` los
                # otros 40 volverían a contarse en cada ciclo. La tarea correría
                # para siempre devolviendo `no_op`, que es justo lo que hace
                # parecer vivo un panel muerto.
                #
                # Va **antes** de la evidencia a propósito: si el planner no
                # encuentra ningún candidato medible, la reparación no es bajar
                # el listón de la sonda sino producir algo que sí se pueda
                # medir. El 2026-08-26 eran 0 de 149.
                base_destilar = """SELECT COUNT(*) AS cnt FROM learning_queue p
                        WHERE p.status = 'internally_checked'
                          AND p.source_type = 'web'
                          AND NOT EXISTS (
                            SELECT 1 FROM learning_queue h
                            WHERE h.source_type = 'distilled'
                              AND h.source_ref = 'candidate:' || p.candidate_id)
                          {intentos}"""
                intentos_sql = """AND NOT EXISTS (
                            SELECT 1 FROM learning_distillation_attempts a
                            WHERE a.candidate_id = p.candidate_id)"""
                try:
                    try:
                        sin_destilar = conn.execute(
                            base_destilar.format(intentos=intentos_sql)
                        ).fetchone()
                    except sqlite3.OperationalError:
                        # `learning_distillation_attempts` la crea el promotor la
                        # primera vez que corre. Si aquí se contara 0 por no
                        # existir, la tarea no se encolaría nunca y la tabla no
                        # llegaría a crearse: arranque en frío bloqueado por sí
                        # mismo. Sin la tabla, ningún padre tiene intento.
                        sin_destilar = conn.execute(
                            base_destilar.format(intentos="")
                        ).fetchone()
                    sin_destilar_cnt = (
                        int(sin_destilar["cnt"] or 0) if sin_destilar else 0
                    )
                except sqlite3.Error:
                    sin_destilar_cnt = 0
                if sin_destilar_cnt > 0:
                    tasks.append(
                        PlannedTask(
                            task_type="learning_claim_distillation",
                            priority=6,
                            reason=f"{sin_destilar_cnt} fuentes web sin destilar",
                            source="mission_planner_baseline",
                            planner_score=min(1.0, 0.4 + sin_destilar_cnt / 200),
                        )
                    )

                # learning_evidence_generation: un candidato elegible por ciclo.
                # Gasta inferencias, así que se pide de uno en uno. Ese ritmo es
                # el único freno real de esta rama —el worker no consulta al
                # metabolismo—, así que no se toca.
                #
                # Dos correcciones sobre la selección anterior (F-037):
                #
                # 1. Filtraba por `source_type='experience'` y de los 665
                #    candidatos `internally_checked` sólo **uno** lo cumplía. Los
                #    otros 664 —`tool`, `conversation`, `qualia_bus`, `web`— no
                #    eran menos aprendizaje: quedaban fuera sin motivo escrito.
                # 2. Elegía sin mirar si el candidato es medible. Cuando no lo
                #    era, el handler salía con `no_op` sin escribir en
                #    `learning_evidence`, el `NOT EXISTS` seguía siendo cierto y
                #    el planner volvía a elegir el mismo para siempre: 400 de las
                #    400 últimas tareas sobre el mismo `candidate_id`, y los 465
                #    eventos registrados diciendo `sin_prueba_objetiva`.
                #
                # Ahora se pide una tanda por antigüedad y se entrega el primero
                # que `build_probe` sabe convertir en pregunta con respuesta
                # comprobable. Preguntarle a la sonda aquí cuesta una regex sobre
                # el contenido ya leído; equivocarse costaba un ciclo entero.
                #
                # El `try` no es decorativo: `learning_evidence` no está en
                # `schemas.sql`, la crea `LearningEvidenceBridge` la primera vez
                # que se usa. En una instalación recién montada la tabla no
                # existe todavía, y sin este `except` el `sqlite3.Error` se
                # llevaba por delante **todo** el bloque base —dedupe, gobernanza
                # semántica, autopromoción—, no sólo esta rama.
                # 3. Ordenaba sólo por `id DESC`, y eso dejaba fuera justo a los
                #    candidatos que más se han usado. La medición y el uso real
                #    son dos ejes independientes: `mark_used_in_run` sube el
                #    contador, pero para promover exige además evidencia del
                #    Measurement Core. El 2026-08-03 las dos poblaciones eran
                #    **disjuntas**: los 16 candidatos con uso probado (hasta 44
                #    usos, media 0.934) eran los ids 1..16 —los primeros que se
                #    escribieron— y caían en las posiciones 632..647 de este
                #    escaneo, con `EVIDENCE_SCAN_LIMIT = 200`. Nunca entraban en
                #    la tanda. Las 976 ejecuciones de `learning_evidence_generation`
                #    midieron siempre candidatos sin un solo uso, y ningún
                #    candidato del sistema llegó jamás a tener los dos ejes a la
                #    vez: cero promociones a `validated_in_runs` en toda la vida
                #    de la base.
                #
                #    Ahora el uso acumulado manda sobre la novedad. No es una
                #    preferencia estética: medir lo que ya se está usando es lo
                #    único que puede cerrar la cadena hasta consolidación.
                #    `run_use_count` no está en `schemas.sql`: la añade la
                #    migración de `LearningPipeline`. Ordenar por una columna que
                #    puede no existir todavía rompía la consulta **y su
                #    fallback**, y con las dos rotas se caía el bloque baseline
                #    entero —dedupe, gobernanza semántica, autopromoción— igual
                #    que describe el comentario de arriba. Se comprueba antes en
                #    vez de confiar en el `except`.
                columnas = {
                    str(fila[1])
                    for fila in conn.execute("PRAGMA table_info(learning_queue)")
                }
                orden = (
                    "ORDER BY run_use_count DESC, id DESC LIMIT ?"
                    if "run_use_count" in columnas
                    else "ORDER BY id DESC LIMIT ?"
                )
                # Sólo el canónico de cada grupo compite: generar evidencia
                # para 104 copias de la misma plantilla es medir 104 veces lo
                # mismo. El filtro va aparte porque su tabla puede faltar, y
                # colarlo en el respaldo de abajo tumbaría la condición «sin
                # evidencia» y devolvería el livelock que ese respaldo evita.
                grupos = """AND NOT EXISTS (
                            SELECT 1 FROM learning_candidate_groups g
                            WHERE g.member_candidate_id = learning_queue.candidate_id
                              AND g.member_candidate_id != g.canonical_candidate_id)"""
                consulta = f"""SELECT candidate_id, content FROM learning_queue
                        WHERE status = 'internally_checked'
                          AND NOT EXISTS (
                            SELECT 1 FROM learning_evidence e
                            WHERE e.candidate_id = learning_queue.candidate_id)
                          {{grupos}}
                        {orden}"""
                try:
                    try:
                        elegibles = conn.execute(
                            consulta.format(grupos=grupos),
                            (self.EVIDENCE_SCAN_LIMIT,),
                        ).fetchall()
                    except sqlite3.OperationalError:
                        # Falta la tabla de grupos, no la de evidencia.
                        elegibles = conn.execute(
                            consulta.format(grupos=""),
                            (self.EVIDENCE_SCAN_LIMIT,),
                        ).fetchall()
                except sqlite3.Error:
                    # Sin tabla de evidencia, ningún candidato la tiene.
                    elegibles = conn.execute(
                        f"""SELECT candidate_id, content FROM learning_queue
                        WHERE status = 'internally_checked'
                        {orden}""",
                        (self.EVIDENCE_SCAN_LIMIT,),
                    ).fetchall()
                medible = next(
                    (
                        fila
                        for fila in elegibles
                        if extract_target(str(fila["content"] or ""))
                    ),
                    None,
                )
                if medible is not None:
                    tasks.append(
                        PlannedTask(
                            task_type="learning_evidence_generation",
                            priority=7,
                            reason=f"candidato {medible['candidate_id']} sin evidencia",
                            source="mission_planner_baseline",
                            planner_score=0.8,
                            payload={"candidate_id": str(medible["candidate_id"])},
                        )
                    )

                # semantic_memory_governance: solo si hay documentos o actividad.
                #
                # Contaba sobre `semantic_memory`, que quedó atrás cuando la
                # ingesta pasó a `semantic_documents`: 0 filas frente a 186
                # `candidate`, así que `sm_cnt` era siempre 0 y la tarea no se
                # encoló ni una vez en 4 777. El handler existía; la condición
                # que lo pide, no.
                #
                # El corte usa `strftime(...'T'...)` porque las tablas guardan
                # ISO-8601 con `T` y `datetime('now')` con espacio: comparados
                # como texto, la ventana se ensancha sola.
                sm = conn.execute(
                    """SELECT COUNT(*) as cnt FROM semantic_documents
                    WHERE status IN ('candidate', 'experimental')
                    OR updated_at > strftime('%Y-%m-%dT%H:%M:%S', 'now', '-6 hours')"""
                ).fetchone()
                sm_cnt = int(sm["cnt"] or 0) if sm else 0
                if sm_cnt > 0:
                    tasks.append(
                        PlannedTask(
                            task_type="semantic_memory_governance",
                            priority=13,
                            reason=f"{sm_cnt} documentos semánticos candidate/experimental",
                            source="mission_planner_baseline",
                            planner_score=min(1.0, 0.5 + sm_cnt / 20),
                        )
                    )

                # neuron_autopromotion: solo si hay evidencia suficiente
                ns = conn.execute(
                    """SELECT COUNT(DISTINCT n.id) as cnt
                    FROM neurons n
                    LEFT JOIN neuron_training nt ON nt.neuron_id = n.id
                    LEFT JOIN neuron_activity na ON na.neuron_id = n.id
                    WHERE n.status IN ('experimental', 'candidate', 'candidate_reviewable')
                    AND nt.score >= 0.65
                    AND na.id IS NOT NULL
                    AND COALESCE(na.policy, '') != 'experimental_light_pulse'"""
                ).fetchone()
                ns_cnt = int(ns["cnt"] or 0) if ns else 0
                if ns_cnt > 0:
                    tasks.append(
                        PlannedTask(
                            task_type="neuron_autopromotion",
                            priority=15,
                            reason=f"{ns_cnt} neuronas promovibles con training o evidencia",
                            source="mission_planner_baseline",
                            planner_score=min(1.0, 0.55 + ns_cnt / 20),
                        )
                    )
        except MISSION_PLANNER_ERRORS as exc:
            record_internal_error(
                "mission_planner.baseline",
                exc,
                payload={
                    "module": __name__,
                    "function": "_plan_baseline",
                    "operation": "baseline_sql_queries",
                },
                db_path=self.db_path,
            )

        return tasks

    def _plan_pending_learning(self) -> list[PlannedTask]:
        """Encola revisión de candidatos de aprendizaje pendientes."""
        tasks: list[PlannedTask] = []
        try:
            with closing(self._connect()) as conn, conn:
                rows = conn.execute(
                    """SELECT id, title, source_type, risk_level, confidence, status
                    FROM learning_queue
                    WHERE status IN ('candidate', 'evaluated')
                    ORDER BY confidence DESC, id ASC
                    LIMIT 5"""
                ).fetchall()
            for row in rows:
                confidence = float(row["confidence"] or 0)
                priority = 6 if confidence >= 0.7 else 7
                tasks.append(
                    PlannedTask(
                        task_type="pending_learning_review",
                        priority=priority,
                        reason=f"Candidato de aprendizaje '{(row['title'] or '')[:40]}' "
                        f"status={row['status']} confidence={confidence:.2f}",
                        source="mission_planner",
                        planner_score=max(0.1, min(1.0, confidence)),
                        related_candidate_id=int(row["id"]),
                        payload={
                            "candidate_id": int(row["id"]),
                            "source_type": row["source_type"],
                        },
                    )
                )
        except MISSION_PLANNER_ERRORS as exc:
            record_internal_error(
                "mission_planner.pending_learning",
                exc,
                payload={
                    "module": __name__,
                    "function": "_plan_pending_learning",
                    "operation": "select_learning_queue",
                },
                db_path=self.db_path,
            )
        return tasks

    def _plan_failed_recent(self) -> list[PlannedTask]:
        """Reintenta tareas fallidas recientes (una vez)."""
        tasks: list[PlannedTask] = []
        try:
            with closing(self._connect()) as conn, conn:
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
                tasks.append(
                    PlannedTask(
                        task_type=str(row["task_type"]),
                        priority=40,
                        reason=f"Reintento de tarea fallida: {row['task_type']} error={(row['error'] or '')[:60]}",
                        source="mission_planner_retry",
                        planner_score=0.55,
                        payload={
                            **payload,
                            "retried": True,
                            "original_task_id": int(row["id"]),
                        },
                    )
                )
        except MISSION_PLANNER_ERRORS as exc:
            record_internal_error(
                "mission_planner.failed_recent",
                exc,
                payload={
                    "module": __name__,
                    "function": "_plan_failed_recent",
                    "operation": "select_failed_worker_tasks",
                },
                db_path=self.db_path,
            )
        return tasks

    def _plan_peft_canary_observation(self) -> list[PlannedTask]:
        """Observa el canary PEFT abierto, si lo hay.

        `GovernedPeftServing` está bien construido —integridad, dataset
        autorizado, métricas OOD, rechazo de olvido catastrófico y activación con
        firma humana— pero nadie lo alimentaba: su único llamador era
        `scripts/run_phase_13_lora_canary.py`. La versión inscrita el 2026-07-29
        llevaba cinco días en `canary` al 5 % con **una** observación, la de su
        propio minuto de creación. Ni graduaba ni revertía.

        Es el mismo agujero que tenía `self_improvement_canary_observation` antes
        de tener productor, y se cierra igual: cada ciclo aporta lo que haya y se
        va. La activación sigue siendo humana; esto sólo acumula la evidencia
        sobre la que decidir.
        """
        try:
            with closing(self._connect()) as conn, conn:
                if not conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='governed_peft_versions'"
                ).fetchone():
                    return []
                fila = conn.execute(
                    "SELECT version_id, adapter_path FROM governed_peft_versions "
                    "WHERE status = 'canary' ORDER BY created_at LIMIT 1"
                ).fetchone()
            if fila is None:
                return []
            return [
                PlannedTask(
                    task_type="peft_canary_observation",
                    priority=34,
                    reason=(
                        f"canary PEFT {fila['version_id']} abierto: acumular "
                        "observaciones para decidir graduación o rollback"
                    ),
                    source="open_peft_canary",
                    planner_score=0.6,
                    payload={
                        "version_id": str(fila["version_id"] or ""),
                        "adapter_path": str(fila["adapter_path"] or ""),
                    },
                )
            ]
        except MISSION_PLANNER_ERRORS as exc:
            record_internal_error(
                "mission_planner.peft_canary", exc, db_path=self.db_path
            )
        return []

    def _plan_memory_consolidation(self) -> list[PlannedTask]:
        """Programa consolidación sólo si hay algo que el handler pueda consolidar.

        Pedía `status = 'validated_in_runs'` y esa tabla tenía cero filas desde
        siempre, así que la tarea no se encoló ni una vez: la última etapa del
        aprendizaje era inalcanzable. La medición hoy termina en
        `evidence_verified` —misma exigencia de mejora medida—, y esa vía no
        estaba contemplada aquí.

        La cuenta replica además los dos umbrales numéricos de
        `LearningPipeline.consolidate()`. Si sólo mirase el estado, encolaría una
        tarea que el handler rechazaría entera por `run_uses` insuficiente, y
        volvería a encolarla el ciclo siguiente: el mismo livelock que ya costó
        465 intentos idénticos en la rama de evidencia (F-037).
        """
        tasks: list[PlannedTask] = []
        try:
            # Los estados salen de `LearningPipeline.CONSOLIDATABLE_STATES`, no de
            # una copia local. Aquí había una lista escrita a mano a la que le
            # faltaba `internally_checked`, que es justo donde vive el uso real:
            # medido el 2026-08-08, `internally_checked` tenía 712 candidatos con
            # 19 usados —hasta 44 usos y 0.936 de score— y `evidence_verified`
            # tenía 10 sin un solo uso. Dos poblaciones disjuntas: la consulta
            # miraba la que no se usa, y 16 candidatos que ya cumplían ambos
            # umbrales no consolidaban nunca.
            #
            # Es la misma forma del fallo que documenta `CONSOLIDATABLE_STATES` en
            # su propio docstring, un escalón más arriba: quien mantiene su copia
            # del vocabulario se queda atrás cuando el dueño lo amplía. Los dos
            # umbrales numéricos ya se leían de allí; los estados no.
            #
            # Esto no relaja nada: `consolidate()` sigue exigiendo
            # `run_use_count >= MIN_RUN_USES` y `avg_outcome_score >=
            # MIN_OUTCOME_SCORE` sea cual sea el estado de entrada, y la consulta
            # los sigue comprobando aquí para no encolar lo que el handler
            # rechazaría (F-037).
            estados = LearningPipeline.CONSOLIDATABLE_STATES
            huecos = ",".join("?" for _ in estados)
            with closing(self._connect()) as conn, conn:
                columnas = {
                    str(column["name"])
                    for column in conn.execute(
                        "PRAGMA table_info(learning_queue)"
                    ).fetchall()
                }
                required = {"status", "run_use_count", "avg_outcome_score"}
                if not required.issubset(columnas):
                    return tasks
                row = conn.execute(
                    f"""SELECT COUNT(*) as cnt FROM learning_queue
                    WHERE status IN ({huecos})
                      AND run_use_count >= ?
                      AND avg_outcome_score >= ?""",
                    (
                        *estados,
                        LearningPipeline.MIN_RUN_USES,
                        LearningPipeline.MIN_OUTCOME_SCORE,
                    ),
                ).fetchone()
                cnt = int(row["cnt"] or 0) if row else 0
            if cnt > 0:
                tasks.append(
                    PlannedTask(
                        task_type="stable_consolidation_review",
                        priority=35,
                        reason=f"{cnt} candidatos validados en runs pendientes de consolidar",
                        source="mission_planner",
                        planner_score=min(1.0, 0.5 + cnt / 10),
                        payload={"pending_count": cnt},
                    )
                )
        except MISSION_PLANNER_ERRORS as exc:
            record_internal_error(
                "mission_planner.memory_consolidation",
                exc,
                payload={
                    "module": __name__,
                    "function": "_plan_memory_consolidation",
                    "operation": "count_verified_learning",
                },
                db_path=self.db_path,
            )
        return tasks

    def _plan_active_missions(self) -> list[PlannedTask]:
        """Programa misiones solo cuando existe evidencia externa nueva."""
        tasks: list[PlannedTask] = []
        try:
            store = NeuronMissionStore(db_path=self.db_path)
            missions = store.list_missions(status="experimental", limit=5)
            missions.extend(store.list_missions(status="stable", limit=5))
            for m in missions:
                with closing(self._connect()) as conn, conn:
                    evidence = conn.execute(
                        """SELECT id,source,refs_json FROM neuron_evidence
                        WHERE mission_id=? AND source NOT IN ('worker','experimental_light_pulse')
                        AND created_at > COALESCE(
                            (SELECT MAX(created_at) FROM neuron_work_cycles WHERE mission_id=?),
                            '1970-01-01'
                        ) ORDER BY id DESC LIMIT 1""",
                        (m.id, m.id),
                    ).fetchone()
                if evidence is None:
                    continue
                tasks.append(
                    PlannedTask(
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
                            "evidence_refs": json.loads(evidence["refs_json"] or "[]"),
                            "evidence_origin": str(evidence["source"]),
                        },
                    )
                )
        except MISSION_PLANNER_ERRORS as exc:
            record_internal_error(
                "mission_planner.active_missions",
                exc,
                payload={
                    "module": __name__,
                    "function": "_plan_active_missions",
                    "operation": "list_experimental_missions",
                },
                db_path=self.db_path,
            )
        return tasks

    def _plan_federation_inbox(self) -> list[PlannedTask]:
        """Revisa inbox de federación si hay nodos con mensajes."""
        tasks: list[PlannedTask] = []
        try:
            with closing(self._connect()) as conn, conn:
                row = conn.execute(
                    """SELECT COUNT(*) as cnt FROM federated_exchange_log
                    WHERE decision = 'pending'
                    AND created_at > datetime('now', '-1 hour')"""
                ).fetchone()
                cnt = int(row["cnt"] or 0) if row else 0
            if cnt > 0:
                tasks.append(
                    PlannedTask(
                        task_type="federation_inbox_review",
                        priority=30,
                        reason=f"{cnt} mensajes federados pendientes",
                        source="mission_planner",
                        planner_score=min(1.0, 0.5 + cnt / 10),
                        payload={"pending_count": cnt},
                    )
                )
        except MISSION_PLANNER_ERRORS as exc:
            record_internal_error(
                "mission_planner.federation_inbox",
                exc,
                payload={
                    "module": __name__,
                    "function": "_plan_federation_inbox",
                    "operation": "count_pending_federation",
                },
                db_path=self.db_path,
            )
        return tasks

    def _plan_system_debt(self) -> list[PlannedTask]:
        """Programa el escaneo de deuda, priorizado por la deuda ya medida.

        Hasta aquí la prioridad salía de una proporción entre runs y episodios:
        un indicio indirecto que no sabe nada de módulos sin importador ni de
        tablas que nadie lee. Los grafos internos sí lo saben, y estaban sólo
        para que los mirara un auditor externo —`unexecuted_task_types()`, cuyo
        docstring dice "atajo para quien quiera actuar sobre la deuda", no la
        llamaba nadie salvo un test—.

        Ahora el informe entra en la planificación: cuanta más deuda medida, más
        prioridad tiene volver a mirarse. Se lee con `allow_build=False` porque
        planificar no puede costar un escaneo del AST; si no hay grafos, se cae
        al indicio anterior en vez de quedarse ciego.
        """
        tasks: list[PlannedTask] = []
        medido = self._debt_snapshot()
        if medido is not None:
            total, resumen = medido
            if total:
                tasks.append(
                    PlannedTask(
                        task_type="system_debt_scan",
                        priority=max(10, 45 - min(35, total)),
                        reason=f"deuda estructural medida: {resumen}",
                        source="internal_graphs",
                        planner_score=min(1.0, total / 60),
                        payload={"debt_items_total": total, "evidence": resumen},
                    )
                )
            return tasks
        try:
            with closing(self._connect()) as conn, conn:
                row = conn.execute(
                    """SELECT COUNT(*) as cnt FROM runs WHERE status = 'ok'
                    AND source NOT LIKE 'system_pulse%'
                    AND source NOT IN ('worker','neuron_activity','test','api-test-context')"""
                ).fetchone()
                runs_ok = int(row["cnt"] or 0) if row else 0
                row2 = conn.execute(
                    """SELECT COUNT(*) as cnt FROM episodic_memory e
                    JOIN runs r ON r.run_id=e.run_id
                    WHERE r.source NOT LIKE 'system_pulse%'
                    AND r.source NOT IN ('worker','neuron_activity','test','api-test-context')"""
                ).fetchone()
                episodes = int(row2["cnt"] or 0) if row2 else 0
            if runs_ok > 5 and episodes < runs_ok * 2:
                tasks.append(
                    PlannedTask(
                        task_type="system_debt_scan",
                        priority=45,
                        reason=f"Deuda detectada: {runs_ok} runs pero solo {episodes} episodios",
                        source="mission_planner",
                        planner_score=min(1.0, (runs_ok - episodes) / max(1, runs_ok)),
                        payload={"runs_ok": runs_ok, "episodes": episodes},
                    )
                )
        except MISSION_PLANNER_ERRORS as exc:
            record_internal_error(
                "mission_planner.system_debt",
                exc,
                payload={
                    "module": __name__,
                    "function": "_plan_system_debt",
                    "operation": "count_runs_and_episodes",
                },
                db_path=self.db_path,
            )
        return tasks

    def _debt_snapshot(self) -> tuple[int, str] | None:
        """Deuda medida en los grafos, o `None` si no hay grafos que leer.

        `None` no es cero: significa "no lo sé". Quien llama debe caer al indicio
        anterior, nunca dar por bueno que no hay deuda.
        """
        try:
            from triade.observability.introspection import build_debt_report

            report = build_debt_report(
                Path(__file__).resolve().parents[2],
                db_path=self.db_path,
                allow_build=False,
            )
        except Exception as exc:  # noqa: BLE001 — la planificación no puede caer
            record_internal_error(
                "mission_planner.debt_snapshot",
                exc,
                payload={"module": __name__, "function": "_debt_snapshot"},
                db_path=self.db_path,
            )
            return None
        if report.get("status") != "measured":
            return None
        items = report.get("items") or {}
        peores = sorted(
            ((name, entry["count"]) for name, entry in items.items() if entry["count"]),
            key=lambda pair: -pair[1],
        )[:3]
        resumen = ", ".join(
            f"{name.replace('_', ' ')} {count}" for name, count in peores
        )
        return int(report.get("debt_items_total") or 0), resumen or "sin categorías"

    def _plan_neuron_formation(self) -> list[PlannedTask]:
        """Evalúa si hay candidatos neuronales sin training."""
        tasks: list[PlannedTask] = []
        try:
            with closing(self._connect()) as conn, conn:
                row = conn.execute(
                    """SELECT COUNT(*) as cnt FROM neurons
                    WHERE status IN ('candidate', 'candidate_reviewable')"""
                ).fetchone()
                cnt = int(row["cnt"] or 0) if row else 0
            if cnt > 0:
                tasks.append(
                    PlannedTask(
                        task_type="neuron_candidate_formation",
                        priority=28,
                        reason=f"{cnt} candidatos neuronales pendientes de evaluación",
                        source="mission_planner",
                        planner_score=min(1.0, 0.5 + cnt / 10),
                        payload={"pending_candidates": cnt},
                    )
                )
        except MISSION_PLANNER_ERRORS as exc:
            record_internal_error(
                "mission_planner.neuron_formation",
                exc,
                payload={
                    "module": __name__,
                    "function": "_plan_neuron_formation",
                    "operation": "count_candidate_neurons",
                },
                db_path=self.db_path,
            )
        return tasks

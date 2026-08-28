"""Central planifica el aprendizaje: de una observación a un plan con dependencias.

Antes de este módulo el aprendizaje era una cadena ciega. `post_run_learning`
encolaba `learning_candidate_generation` directamente en `autonomous_tasks`, sin
`goal_id`, y las etapas posteriores las reponía `MissionPlanner` mirando el
estado de la base. Medido sobre la base viva el 2026-08-28: **737 tareas de
`learning_candidate_generation` y 0 con `goal_id`**; lo mismo en las otras siete
familias de aprendizaje —16.000 tareas, ninguna enlazada—. Como
`GoalOrchestrator.record_task_result` sale en la primera línea cuando falta el
`goal_id`, Central no se enteraba nunca de que el aprendizaje había ocurrido, ni
de qué candidato salió, ni de si hubo evidencia.

Nada de eso se sustituye aquí. Se **conecta**:

- el planificador durable sigue siendo `PlanningGraph` (no hay uno nuevo);
- la cola sigue siendo `WorkerTaskQueue` sobre `autonomous_tasks`;
- la clasificación reutiliza el clasificador de `ExperienceLearningCandidateProducer`;
- las etapas siguen siendo los mismos cinco tipos de tarea que ya existían.

Lo que faltaba y se añade es el razonamiento entre medias: **observar,
clasificar, buscar si ya se sabe, decidir, y sólo entonces planificar** —con
dependencias reales entre etapas, que `PlanningGraph` sabía representar desde el
principio (`goal_dependencies`, `get_ready_goals`) y que no usaba nadie: cero
filas en producción.

La regla de sincronía se mantiene intacta: aquí no se llama desde el camino de
respuesta. `post_run` escribe una fila y sale; este módulo corre después, dentro
de un worker.
"""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from triade.db import sqlite3
from triade.workers.task_queue import WorkerTaskQueue

from .planning_graph import GOAL_TERMINAL_STATES, PlanningGraph

#: Las cinco etapas del aprendizaje, en el orden en que se pueden ejecutar y
#: con la dependencia que justifica ese orden. No es una preferencia de estilo:
#: cada una necesita la fila que escribe la anterior.
#:
#: - no se deduplica un candidato que todavía no existe;
#: - no se destila una afirmación de un grupo que no se ha formado;
#: - no se mide evidencia de una afirmación sin sujeto;
#: - no se evalúa lo que no se ha medido.
LEARNING_STAGES: tuple[tuple[str, str, str], ...] = (
    (
        "extract",
        "learning_candidate_generation",
        "Extraer la proposición aprendible del run",
    ),
    (
        "dedupe",
        "learning_candidate_deduplication",
        "Agrupar el candidato con sus duplicados",
    ),
    (
        "evidence",
        "learning_evidence_generation",
        "Medir evidencia objetiva del candidato",
    ),
    (
        "evaluate",
        "pending_learning_review",
        "Evaluar y verificar el candidato medido",
    ),
)

#: `learning_claim_distillation` **no** está en el plan de una conversación, y
#: no es un olvido. `AssertionPromoter` sólo da hijo sondeable a los candidatos
#: de origen `web`; sobre uno de `experience` no hace nada. Planificar una etapa
#: que por construcción no puede tener efecto es decorar el grafo, que es
#: justamente lo que esta auditoría persigue. Sigue viva para el barrido de
#: `MissionPlanner`, que es donde tiene sentido.
STAGES_NOT_APPLICABLE_TO_CONVERSATION = ("learning_claim_distillation",)

#: Etapas cuyo handler exige un `candidate_id` en el payload. Sin él devuelven
#: `no_op` con `skipped_reason: sin_candidate_id`: la cadena parecería completa y
#: no habría medido nada. El id lo produce `extract` y Central lo arrastra.
STAGES_REQUIRING_CANDIDATE = frozenset({"evidence"})

#: Disposiciones que Central puede decidir sobre una observación.
DISPOSITIONS = (
    "ignore",
    "update_memory",
    "update_existing_neuron",
    "create_neuron_candidate",
)

#: Palabras vacías del castellano que no distinguen una habilidad de otra. Sin
#: quitarlas, «quiero que me hagas una imagen» y «quiero que aprendas a hacer
#: imágenes» comparten sobre todo `quiero/que/me/una`, y el parecido sale de las
#: palabras de relleno en vez de la habilidad.
_VACIAS = frozenset(
    [
        "a",
        "al",
        "algo",
        "ahora",
        "aprende",
        "aprendas",
        "asi",
        "como",
        "con",
        "contra",
        "cual",
        "cuando",
        "de",
        "del",
        "desde",
        "donde",
        "dos",
        "el",
        "ella",
        "ellas",
        "ello",
        "ellos",
        "en",
        "entre",
        "era",
        "eres",
        "es",
        "esa",
        "ese",
        "eso",
        "esta",
        "este",
        "esto",
        "ha",
        "haber",
        "habia",
        "hace",
        "hacer",
        "hacia",
        "hagas",
        "han",
        "has",
        "hasta",
        "hay",
        "la",
        "las",
        "le",
        "les",
        "lo",
        "los",
        "mas",
        "me",
        "mi",
        "mientras",
        "mucho",
        "muy",
        "nada",
        "ni",
        "no",
        "nos",
        "nosotros",
        "o",
        "os",
        "otra",
        "otro",
        "para",
        "pero",
        "poco",
        "por",
        "porque",
        "que",
        "qué",
        "quien",
        "quiero",
        "se",
        "ser",
        "si",
        "sin",
        "sobre",
        "su",
        "sus",
        "también",
        "tanto",
        "te",
        "tener",
        "tiene",
        "todo",
        "tu",
        "tus",
        "un",
        "una",
        "uno",
        "unos",
        "ya",
        "yo",
    ]
)

#: Cuánto solapamiento de términos significativos basta para considerar que dos
#: misiones son la misma habilidad dicha de dos maneras. 0,5 sobre el
#: vocabulario significativo del más corto: exigir más deja pasar
#: «hacer imagen» / «hacer imágenes digitales», que es exactamente el caso que
#: pobló la base de neuronas gemelas.
NEURON_DEDUP_THRESHOLD = 0.5


def _normalizar(texto: str) -> str:
    plano = unicodedata.normalize("NFKD", str(texto or "").lower())
    plano = plano.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", plano)).strip()


def _terminos(texto: str) -> set[str]:
    """Términos significativos, con la raíz recortada.

    El recorte a 5 caracteres es tosco a propósito: no hace falta un lematizador
    para que «imagen», «imagenes» e «imágenes» caigan en el mismo cubo, y un
    lematizador sería una dependencia nueva para resolver un problema de tres
    letras.
    """
    palabras = [
        p for p in _normalizar(texto).split() if len(p) > 2 and p not in _VACIAS
    ]
    return {p[:5] for p in palabras}


def _parecido(a: str, b: str) -> float:
    ta, tb = _terminos(a), _terminos(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def find_equivalent_neuron(
    db_path: str | Path, mission: str
) -> tuple[dict[str, Any] | None, float]:
    """La neurona ya registrada que cubre esta misma habilidad, si la hay.

    Se compara la **misión**, no el nombre. El nombre es un slug del mensaje
    (`_slug(input_packet.user_input)`), así que dos formas de pedir lo mismo dan
    dos nombres distintos y la comparación por nombre —la única que había— nunca
    encuentra nada. Medido sobre la base viva el 2026-08-28: de 40 neuronas, 28
    llevan el nombre de un mensaje, y hay **seis** para «hacer imágenes»
    (`quiero-hagas-imagen`, `pero-quiero-hagas-imagen`, `quiero-hagas-imagen-casa`,
    `aprende-imagenes-digitales`, `quiero-aprendas-hacer-imagenes`,
    `quiero-aprendas-verdad-imagenes`) y dos para bajarse un modelo.

    Devuelve también el parecido para que quien decide pueda registrar por qué.
    """
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            filas = conn.execute(
                "SELECT id,name,status,domain,mission FROM neurons"
                " WHERE status IN"
                " ('candidate','candidate_reviewable','experimental','stable')"
            ).fetchall()
    except sqlite3.Error:
        return None, 0.0
    mejor, mejor_score = None, 0.0
    for fila in filas:
        texto = f"{fila['mission'] or ''} {fila['name'] or ''}"
        score = _parecido(mission, texto)
        if score > mejor_score:
            mejor, mejor_score = fila, score
    if mejor is None or mejor_score < NEURON_DEDUP_THRESHOLD:
        return None, round(mejor_score, 3)
    return {
        "neuron_id": int(mejor["id"]),
        "name": str(mejor["name"]),
        "status": str(mejor["status"]),
        "domain": str(mejor["domain"] or ""),
        "mission": str(mejor["mission"] or ""),
    }, round(mejor_score, 3)


class CentralLearningPlanner:
    """La autoridad de aprendizaje. Decide qué hacer con una experiencia.

    No ejecuta nada: decide, planifica y observa. La ejecución es de los
    workers, y el gobierno de la Constitución.
    """

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.graph = PlanningGraph(self.db_path)
        self.queue = WorkerTaskQueue(self.db_path)

    # ── 1. CLASIFICAR ────────────────────────────────────────────────

    def classify(self, observation: dict[str, Any]) -> dict[str, Any]:
        """Qué clase de cosa es esto, si es que es alguna.

        Se pregunta al **mismo** productor que ejecutará la etapa de extracción,
        no a un clasificador propio. Dos opiniones distintas sobre el mismo texto
        producirían el peor de los mundos: Central planificando cuatro tareas
        para una experiencia que el extractor va a rechazar en la primera.

        `produce()` no escribe nada —`persist()` es un método aparte— y no gasta
        inferencia: son expresiones regulares y el veredicto de seguridad que ya
        gobierna la recuperación.
        """
        from triade.learning.candidate_producer import (
            ExperienceLearningCandidateProducer,
        )

        mensaje = str(observation.get("message") or "")
        producido = ExperienceLearningCandidateProducer(self.db_path).produce(
            run_id=str(observation.get("source_run_id") or ""),
            message=mensaje,
            role=str(observation.get("role") or "user"),
            domain=str(observation.get("domain") or "conversation"),
        )
        if producido.candidates:
            candidato = producido.candidates[0]
            return {
                "learning_type": candidato.type,
                "confidence": float(candidato.explicitness_score),
                "detail": {"risk_level": candidato.risk_level},
                "reason": "proposition_detected",
            }
        rechazo = (
            str(producido.rejected[0]["reason"])
            if producido.rejected
            else "sin_proposicion_explicita"
        )
        # Sin proposición, todavía puede haber una necesidad operativa: eso lo
        # dice la compuerta de neuronas, que ya existe y ya se consulta en el
        # camino síncrono. Aquí se lee su veredicto, no se reescribe.
        from .neuron_candidate_gate import evaluate_neuron_candidate_worthiness

        gate = evaluate_neuron_candidate_worthiness(
            mensaje,
            intent=str(observation.get("intent") or "conversation"),
            domain=str(observation.get("domain") or "") or None,
        )
        if gate.get("should_create_neuron"):
            return {
                "learning_type": "capability",
                "confidence": float(gate.get("score") or 0.0),
                "detail": {"gate_reason": gate.get("reason")},
                "suggested_name": gate.get("suggested_name"),
                "suggested_domain": gate.get("suggested_domain"),
                "reason": "operational_capability_requested",
            }
        return {
            "learning_type": "noise",
            "confidence": float(gate.get("score") or 0.0),
            "detail": {
                "gate_route": gate.get("route"),
                "gate_reason": gate.get("reason"),
                "producer_rejection": rechazo,
            },
            "reason": rechazo,
        }

    # ── 2. BUSCAR LO QUE YA SE SABE ──────────────────────────────────

    def search_existing_knowledge(
        self, observation: dict[str, Any], classification: dict[str, Any]
    ) -> dict[str, Any]:
        """¿Esto ya lo sabe Tríade, o ya tiene una neurona que lo cubre?"""
        mensaje = str(observation.get("message") or "")
        normalizado = _normalizar(mensaje)
        hallazgo: dict[str, Any] = {
            "known_candidate_id": None,
            "similar_neuron": None,
            "neuron_similarity": 0.0,
        }
        if not normalizado:
            return hallazgo
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            fila = conn.execute(
                "SELECT candidate_id,status FROM learning_queue"
                " WHERE normalized_summary=? LIMIT 1",
                (normalizado,),
            ).fetchone()
            if fila is not None:
                hallazgo["known_candidate_id"] = str(fila["candidate_id"])
                hallazgo["known_candidate_status"] = str(fila["status"])
        gemela, parecido = find_equivalent_neuron(self.db_path, mensaje)
        hallazgo["similar_neuron"] = gemela
        hallazgo["neuron_similarity"] = parecido
        return hallazgo

    # ── 3. DECIDIR ───────────────────────────────────────────────────

    @staticmethod
    def decide(
        classification: dict[str, Any], existing: dict[str, Any]
    ) -> dict[str, Any]:
        """Qué hacer. Incluida la opción de no aprender nada."""
        tipo = str(classification.get("learning_type") or "noise")
        if tipo == "noise":
            return {
                "disposition": "ignore",
                "reason": str(classification.get("reason") or "no_learning_signal"),
            }
        if tipo == "capability":
            if existing.get("similar_neuron"):
                return {
                    "disposition": "update_existing_neuron",
                    "reason": "equivalent_capability_already_registered",
                    "neuron": existing["similar_neuron"],
                    "similarity": existing.get("neuron_similarity"),
                }
            return {
                "disposition": "create_neuron_candidate",
                "reason": "new_operational_capability",
            }
        if existing.get("known_candidate_id"):
            return {
                "disposition": "ignore",
                "reason": "identical_proposition_already_in_queue",
                "candidate_id": existing["known_candidate_id"],
            }
        return {"disposition": "update_memory", "reason": f"learnable_{tipo}"}

    # ── 4. PLANIFICAR ────────────────────────────────────────────────

    def plan_from_observation(self, observation: dict[str, Any]) -> dict[str, Any]:
        """El ciclo completo: observar → clasificar → buscar → decidir → planificar."""
        run_id = str(observation.get("source_run_id") or "").strip()
        if not run_id:
            return {"status": "rejected", "reason": "empty_source_run_id"}

        classification = self.classify(observation)
        existing = self.search_existing_knowledge(observation, classification)
        decision = self.decide(classification, existing)
        disposition = str(decision["disposition"])

        root = self.graph.create_goal(
            title=f"Aprendizaje del run {run_id}"[:120],
            description=str(observation.get("message") or "")[:1000],
            priority=2,
            metadata={
                "kind": "learning",
                "run_id": run_id,
                "source": str(observation.get("source") or "conversation"),
                "source_run_id": run_id,
                "learning_type": classification.get("learning_type"),
                "learning_reason": decision.get("reason"),
                "disposition": disposition,
                "confidence": classification.get("confidence"),
                "risk": "low",
                "existing_knowledge": existing,
                "budget": {"max_attempts": 2, "max_steps": len(LEARNING_STAGES)},
            },
        )

        if disposition in {"ignore", "update_existing_neuron"}:
            # No aprender es una decisión, y se registra como tal: un objetivo
            # cerrado con su motivo, no una fila que falta.
            self.graph.transition(
                root.goal_id,
                "blocked",
                actor="central_learning_planner",
                reason=f"{disposition}:{decision.get('reason')}",
                event_type="learning_decision",
                evidence={
                    "classification": classification,
                    "decision": decision,
                    "existing": existing,
                },
            )
            self._record_observation(
                root.goal_id,
                disposition=disposition,
                outcome_status="decided_without_execution",
                evidence={
                    "classification": classification,
                    "decision": decision,
                    "existing": existing,
                },
            )
            return {
                "status": "decided",
                "goal_id": root.goal_id,
                "disposition": disposition,
                "reason": decision.get("reason"),
                "steps": [],
                "task_id": None,
            }

        pasos = self._create_stage_steps(root.goal_id, observation, classification)
        self._record_observation(
            root.goal_id,
            disposition=disposition,
            outcome_status="planned",
            evidence={
                "classification": classification,
                "decision": decision,
                "existing": existing,
                "steps": [p["stage"] for p in pasos],
            },
        )
        arranque = self._enqueue_ready_steps(root.goal_id, observation)
        self.graph.transition(
            root.goal_id,
            "queued",
            actor="central_learning_planner",
            reason="learning_plan_started",
            event_type="task_enqueued",
            evidence={"task_ids": [t["task_id"] for t in arranque]},
        )
        return {
            "status": "planned",
            "goal_id": root.goal_id,
            "disposition": disposition,
            "reason": decision.get("reason"),
            "steps": pasos,
            "task_id": arranque[0]["task_id"] if arranque else None,
            "enqueued": arranque,
        }

    def _create_stage_steps(
        self,
        root_id: str,
        observation: dict[str, Any],
        classification: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Crea las cinco etapas encadenadas por dependencias reales."""
        pasos: list[dict[str, Any]] = []
        anterior: str | None = None
        for indice, (stage, task_type, titulo) in enumerate(LEARNING_STAGES):
            nodo = self.graph.create_goal(
                title=titulo,
                description=f"{stage}:{task_type}",
                parent_id=root_id,
                priority=indice + 1,
                dependencies=[anterior] if anterior else None,
                metadata={
                    "kind": "learning_step",
                    "root_goal_id": root_id,
                    "stage": stage,
                    "worker_task_type": task_type,
                    "stage_index": indice,
                    "source_run_id": observation.get("source_run_id"),
                    "learning_type": classification.get("learning_type"),
                    "success_criteria": _CRITERIOS[stage],
                },
            )
            pasos.append(
                {
                    "stage": stage,
                    "step_id": nodo.goal_id,
                    "task_type": task_type,
                    "depends_on": anterior,
                }
            )
            anterior = nodo.goal_id
        return pasos

    # ── 5. EJECUTAR: sólo lo que tiene las dependencias cumplidas ────

    def ready_steps(self, root_id: str) -> list[Any]:
        """Pasos pendientes cuyas dependencias están todas completadas."""
        listos = []
        for hijo in self.graph.get_children(root_id):
            if hijo.status != "pending":
                continue
            if self.dependencies_satisfied(hijo.goal_id):
                listos.append(hijo)
        return listos

    def dependencies_satisfied(self, step_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            filas = conn.execute(
                """SELECT dep.status AS status FROM goal_dependencies gd
                JOIN planning_graph dep ON gd.depends_on_id = dep.goal_id
                WHERE gd.goal_id = ?""",
                (step_id,),
            ).fetchall()
        return all(str(f["status"]) == "completed" for f in filas)

    def _enqueue_ready_steps(
        self, root_id: str, observation: dict[str, Any]
    ) -> list[dict[str, Any]]:
        encolados = []
        for paso in self.ready_steps(root_id):
            task_type = str(paso.metadata.get("worker_task_type") or "")
            if not task_type:
                continue
            stage = str(paso.metadata.get("stage") or "")
            payload = {
                # Éstos son los dos campos que hacían falta y no estaban: con
                # ellos `worker_loop` llama a `record_task_result` y Central se
                # entera del resultado.
                "goal_id": root_id,
                "goal_step_id": paso.goal_id,
                "worker_task_type": task_type,
                "stage": stage,
                "source_run_id": observation.get("source_run_id"),
                "message": observation.get("message"),
                "response": observation.get("response"),
                "role": observation.get("role") or "user",
                "domain": observation.get("domain") or "conversation",
                "attempt": 1,
                "max_attempts": 2,
                "autonomy_precleared": "central_learning_planner",
            }
            candidate_id = self._candidate_of(root_id)
            if candidate_id:
                payload["candidate_id"] = candidate_id
            elif stage in STAGES_REQUIRING_CANDIDATE:
                # Sin el id que produjo la extracción, medir es imposible y la
                # tarea saldría `no_op` fingiendo que la cadena avanzó. Se
                # bloquea el paso diciendo por qué.
                self.graph.transition(
                    paso.goal_id,
                    "blocked",
                    actor="central_learning_planner",
                    reason="stage_requires_candidate_id_none_produced",
                    event_type="learning_decision",
                )
                continue
            tarea = self.queue.enqueue(task_type, payload=payload, priority=25)
            self.graph.transition(
                paso.goal_id,
                "queued",
                actor="central_learning_planner",
                reason="dependencies_satisfied",
                event_type="task_enqueued",
                evidence={"task_id": tarea.id, "task_type": task_type},
            )
            encolados.append(
                {
                    "step_id": paso.goal_id,
                    "stage": paso.metadata.get("stage"),
                    "task_id": tarea.id,
                    "task_type": task_type,
                }
            )
        return encolados

    def _candidate_of(self, root_id: str) -> str | None:
        """El candidato que produjo la extracción de este plan, si lo hubo."""
        with sqlite3.connect(self.db_path) as conn:
            fila = conn.execute(
                "SELECT json_extract(metadata,'$.candidate_id') FROM planning_graph"
                " WHERE goal_id=?",
                (root_id,),
            ).fetchone()
        valor = str(fila[0]) if fila and fila[0] else ""
        return valor or None

    def remember_candidate(self, root_id: str, candidate_id: str) -> None:
        """Central se queda con el `candidate_id` que produjo su propio plan.

        Es la respuesta literal a «¿conoce Central el candidate_id resultante?».
        Antes no: el handler lo devolvía en el resultado y ese resultado no lo
        leía nadie.
        """
        if not candidate_id:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE planning_graph"
                " SET metadata=json_set(COALESCE(metadata,'{}'),'$.candidate_id',?)"
                " WHERE goal_id=?",
                (str(candidate_id), root_id),
            )

    # ── 6. OBSERVAR EL RESULTADO Y REPLANIFICAR ──────────────────────

    def advance(
        self, root_id: str, *, last_result: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Central recibe el resultado de una etapa y decide qué sigue.

        Tres salidas posibles, y las tres son decisiones distintas:

        - quedan etapas listas → se encolan (avance normal);
        - no quedan etapas y todas terminaron → se cierra el objetivo;
        - la evidencia dice que el resto del plan ya no tiene sentido → se
          **poda** y se cierra. Eso es replanificar, no reintentar: reintentar
          `learning_candidate_generation` sobre un mensaje sin proposición
          vuelve a extraer nada, tres veces.
        """
        raiz = self.graph.get_goal(root_id)
        if raiz is None:
            return {"status": "not_found", "goal_id": root_id}
        if raiz.status in GOAL_TERMINAL_STATES:
            return {
                "status": "already_closed",
                "goal_id": root_id,
                "state": raiz.status,
            }

        if isinstance(last_result, dict) and last_result.get("candidate_id"):
            self.remember_candidate(root_id, str(last_result["candidate_id"]))

        poda = self._prune_reason(last_result)
        if poda is not None:
            podados = self._prune_remaining(root_id, poda)
            self.graph.transition(
                root_id,
                "completed",
                actor="central_learning_planner",
                reason=f"replanned:{poda}",
                event_type="replanned",
                evidence={"pruned_steps": podados, "prune_reason": poda},
            )
            self._record_observation(
                root_id,
                disposition="replanned_no_learning_signal",
                outcome_status="completed",
                evidence={"prune_reason": poda, "pruned_steps": podados},
            )
            return {
                "status": "replanned",
                "goal_id": root_id,
                "reason": poda,
                "pruned": podados,
            }

        observation = {
            "source_run_id": raiz.metadata.get("source_run_id"),
            "message": raiz.description,
            "response": "",
            "domain": raiz.metadata.get("domain") or "conversation",
        }
        encolados = self._enqueue_ready_steps(root_id, observation)
        if encolados:
            return {"status": "advanced", "goal_id": root_id, "enqueued": encolados}

        hijos = self.graph.get_children(root_id)
        if any(h.status not in GOAL_TERMINAL_STATES for h in hijos):
            return {"status": "waiting", "goal_id": root_id}

        completados = [h for h in hijos if h.status == "completed"]
        cerrado = "completed" if completados else "failed"
        self.graph.transition(
            root_id,
            cerrado,
            actor="central_learning_planner",
            reason="all_learning_steps_terminal",
            event_type="goal_closed",
            evidence={
                "completed_steps": len(completados),
                "total_steps": len(hijos),
            },
        )
        self._record_observation(
            root_id,
            disposition="learning_cycle_closed",
            outcome_status=cerrado,
            evidence={
                "completed_steps": len(completados),
                "total_steps": len(hijos),
                "last_result_status": (last_result or {}).get("status"),
            },
        )
        return {"status": cerrado, "goal_id": root_id, "steps": len(hijos)}

    #: Etapas cuyo `no_op` invalida el resto del plan, y por qué.
    #:
    #: - `extract`: no había proposición. Deduplicar, medir y evaluar la nada
    #:   son tres tareas que no pueden salir bien.
    #: - `evidence`: `build_probe` no encontró dato distintivo que preguntar. Sin
    #:   medición no hay nada que evaluar, y `pending_learning_review` volvería a
    #:   elegir al mismo candidato cada ciclo. Es el patrón F-037 medido el
    #:   2026-08-27: 465 intentos idénticos sobre un candidato inmedible.
    _PRUNE_ON_NOOP = frozenset({"extract", "evidence"})

    @classmethod
    def _prune_reason(cls, result: dict[str, Any] | None) -> str | None:
        """¿Dice la evidencia que el resto del plan ya no aplica?

        Esto es replanificar, no reintentar. Reintentar una extracción sobre un
        mensaje sin proposición vuelve a extraer nada, tres veces; medir otra vez
        un candidato sin dato sondeable vuelve a no poder medirlo. Central cambia
        de estrategia —dejar de gastar— en vez de repetir la misma.
        """
        if not isinstance(result, dict):
            return None
        if str(result.get("stage") or "") not in cls._PRUNE_ON_NOOP:
            return None
        if str(result.get("effect") or "") == "no_op":
            return (
                f"{result.get('stage')}:"
                f"{result.get('skipped_reason') or 'no_learning_signal'}"
            )
        return None

    def _prune_remaining(self, root_id: str, reason: str) -> list[str]:
        podados = []
        for hijo in self.graph.get_children(root_id):
            if hijo.status in GOAL_TERMINAL_STATES:
                continue
            self.graph.transition(
                hijo.goal_id,
                "blocked",
                actor="central_learning_planner",
                reason=f"pruned:{reason}",
                event_type="replanned",
                evidence={"prune_reason": reason},
            )
            podados.append(hijo.goal_id)
        return podados

    # ── observabilidad: la cadena entera desde un run ────────────────

    def chain_for_run(self, run_id: str) -> dict[str, Any]:
        """RUN → OBSERVACIÓN → OBJETIVO → PASOS → TAREAS → EVIDENCIA → RESULTADO.

        Todos los identificadores enlazables en una sola lectura. No hay base de
        observabilidad nueva: son las tablas que ya existen, unidas por los
        campos que antes no se escribían (`goal_id` en el payload de la tarea,
        `candidate_id` en la metadata del objetivo).
        """
        cadena: dict[str, Any] = {
            "run_id": run_id,
            "observation": None,
            "goal": None,
            "steps": [],
            "tasks": [],
            "candidate": None,
            "evidence": [],
            "observations": [],
        }
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            observacion = conn.execute(
                """SELECT task_id,task_type,status,created_at FROM autonomous_tasks
                WHERE task_type='central_learning_observation'
                  AND json_extract(payload_json,'$.source_run_id')=?
                ORDER BY created_at DESC LIMIT 1""",
                (run_id,),
            ).fetchone()
            if observacion is not None:
                cadena["observation"] = dict(observacion)
            raiz = conn.execute(
                """SELECT goal_id,title,status,metadata,created_at,completed_at
                FROM planning_graph
                WHERE parent_id IS NULL
                  AND json_extract(metadata,'$.kind')='learning'
                  AND json_extract(metadata,'$.source_run_id')=?
                ORDER BY created_at DESC LIMIT 1""",
                (run_id,),
            ).fetchone()
            if raiz is None:
                return cadena
            meta = json.loads(str(raiz["metadata"] or "{}"))
            cadena["goal"] = {
                "goal_id": str(raiz["goal_id"]),
                "title": str(raiz["title"]),
                "status": str(raiz["status"]),
                "disposition": meta.get("disposition"),
                "learning_type": meta.get("learning_type"),
                "learning_reason": meta.get("learning_reason"),
                "candidate_id": meta.get("candidate_id"),
                "created_at": str(raiz["created_at"]),
                "completed_at": raiz["completed_at"],
            }
            goal_id = str(raiz["goal_id"])
            for hijo in conn.execute(
                """SELECT goal_id,title,status,metadata FROM planning_graph
                WHERE parent_id=? ORDER BY priority,created_at""",
                (goal_id,),
            ).fetchall():
                hijo_meta = json.loads(str(hijo["metadata"] or "{}"))
                dependencias = [
                    str(f["depends_on_id"])
                    for f in conn.execute(
                        "SELECT depends_on_id FROM goal_dependencies WHERE goal_id=?",
                        (hijo["goal_id"],),
                    ).fetchall()
                ]
                cadena["steps"].append(
                    {
                        "step_id": str(hijo["goal_id"]),
                        "stage": hijo_meta.get("stage"),
                        "task_type": hijo_meta.get("worker_task_type"),
                        "status": str(hijo["status"]),
                        "depends_on": dependencias,
                        "success_criteria": hijo_meta.get("success_criteria"),
                    }
                )
            cadena["tasks"] = [
                dict(f)
                for f in conn.execute(
                    """SELECT task_id,task_type,status,
                    json_extract(payload_json,'$.stage') AS stage,
                    json_extract(payload_json,'$.goal_step_id') AS step_id,
                    result_ref,created_at FROM autonomous_tasks
                    WHERE json_extract(payload_json,'$.goal_id')=?
                    ORDER BY created_at""",
                    (goal_id,),
                ).fetchall()
            ]
            cadena["observations"] = [
                dict(f)
                for f in conn.execute(
                    """SELECT observation_id,disposition,outcome_status,created_at
                    FROM goal_learning_observations WHERE goal_id=?
                    ORDER BY created_at""",
                    (goal_id,),
                ).fetchall()
            ]
            candidate_id = meta.get("candidate_id")
            if candidate_id:
                fila = conn.execute(
                    "SELECT candidate_id,status,domain,risk_level,"
                    "substr(content,1,300) AS content FROM learning_queue"
                    " WHERE candidate_id=?",
                    (str(candidate_id),),
                ).fetchone()
                cadena["candidate"] = dict(fila) if fila else None
                try:
                    cadena["evidence"] = [
                        dict(f)
                        for f in conn.execute(
                            "SELECT * FROM learning_evidence WHERE candidate_id=?"
                            " ORDER BY rowid",
                            (str(candidate_id),),
                        ).fetchall()
                    ]
                except sqlite3.Error:
                    cadena["evidence"] = []
        return cadena

    # ── registro ─────────────────────────────────────────────────────

    def _record_observation(
        self,
        goal_id: str,
        *,
        disposition: str,
        outcome_status: str,
        evidence: dict[str, Any],
        task_id: str | None = None,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO goal_learning_observations
                (observation_id,goal_id,task_id,disposition,outcome_status,evidence_json,created_at)
                VALUES(?,?,?,?,?,?,datetime('now'))""",
                (
                    f"central-learning-{uuid.uuid4().hex[:16]}",
                    goal_id,
                    task_id,
                    disposition,
                    outcome_status,
                    json.dumps(
                        evidence, ensure_ascii=False, sort_keys=True, default=str
                    ),
                ),
            )


#: Qué tiene que ser verdad para dar una etapa por buena. Va en la metadata del
#: paso para que la Cabina pueda enseñarlo sin recalcularlo.
_CRITERIOS: dict[str, str] = {
    "extract": "existe fila en learning_queue para el run, o no había proposición",
    "dedupe": "el candidato pertenece a un grupo canónico",
    "evidence": "existe fila en learning_evidence con medición del candidato",
    "evaluate": "el candidato avanzó de estado o quedó rechazado con motivo",
}

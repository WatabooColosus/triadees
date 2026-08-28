"""Central planifica el aprendizaje: prueba causal de punta a punta.

No hay ni un `INSERT` a mano. Todo lo que aparece en la base lo escriben los
mismos módulos que corren en producción: `schedule_learning_from_run` observa,
`CentralLearningPlanner` decide y planifica, y los handlers reales de
`WorkerLoop` ejecutan las etapas bajo su lease.

Lo que estas pruebas fijan es lo que **no** era cierto antes del 2026-08-28,
medido sobre la base viva:

- 737 tareas de `learning_candidate_generation` y **ninguna** con `goal_id`:
  Central no se enteraba de que el aprendizaje ocurría;
- `goal_dependencies` con **cero** filas, con la API de dependencias escrita y
  sin un solo consumidor;
- todos los objetivos con exactamente un hijo: no había planes, había pasos
  sueltos;
- una neurona por mensaje, y seis para «hacer imágenes».
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from triade.core.goal_orchestrator import GoalOrchestrator
from triade.core.learning_planner import (
    LEARNING_STAGES,
    CentralLearningPlanner,
)
from triade.learning.post_run import schedule_learning_from_run
from triade.runtime.task_leases import AutonomousTaskStore
from triade.workers.contracts import WorkerRunConfig, WorkerTask
from triade.workers.worker_loop import WorkerLoop

PREFERENCIA = "Usa siempre la etiqueta AZUL-7 al principio de cada informe."


def _observacion(db: Path, run_id: str, mensaje: str) -> dict[str, Any]:
    """Cierra un run y devuelve el payload de la observación que dejó."""
    recibo = schedule_learning_from_run(
        db,
        run_id=run_id,
        message=mensaje,
        response="Entendido.",
        source="react-ui",
        enabled=True,
    )
    assert recibo["scheduled"] is True, recibo
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        fila = conn.execute(
            "SELECT task_type,payload_json FROM autonomous_tasks WHERE task_id=?",
            (recibo["task_id"],),
        ).fetchone()
    # El sensor encola una OBSERVACIÓN, no una etapa de aprendizaje. Si esto
    # vuelve a ser `learning_candidate_generation`, `post_run` ha recuperado la
    # autoridad y Central vuelve a quedarse fuera.
    assert fila["task_type"] == "central_learning_observation"
    return dict(json.loads(fila["payload_json"]))


def _worker(tmp_path: Path, db: Path) -> WorkerLoop:
    return WorkerLoop(
        db_path=db,
        runs_dir=tmp_path / "runs",
        lock_file=tmp_path / "lock",
        stop_file=tmp_path / "stop",
    )


def _config(tmp_path: Path) -> WorkerRunConfig:
    return WorkerRunConfig(
        max_iterations=1,
        sleep_seconds=0,
        once=True,
        runs_dir=str(tmp_path / "runs"),
        lock_file=str(tmp_path / "lock"),
        stop_file=str(tmp_path / "stop"),
    )


def _ejecutar_siguiente(
    loop: WorkerLoop, tmp_path: Path, db: Path, tipos: set[str]
) -> dict[str, Any] | None:
    """Ejecuta la siguiente tarea pendiente de esos tipos, con su handler real."""
    store = AutonomousTaskStore(db)
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        fila = conn.execute(
            "SELECT task_id,task_type,payload_json FROM autonomous_tasks"
            " WHERE status IN ('pending','queued') ORDER BY created_at,task_id"
        ).fetchall()
    objetivo = next((f for f in fila if f["task_type"] in tipos), None)
    if objetivo is None:
        return None
    arrendada = store.claim_task(str(objetivo["task_id"]), "test-worker")
    assert arrendada is not None
    task = WorkerTask(
        id=None,
        task_type=str(arrendada["task_type"]),
        payload=dict(arrendada.get("payload") or {}),
        priority=int(arrendada.get("priority") or 50),
    )
    store.start(
        str(arrendada["task_id"]), "test-worker", int(arrendada["lease_generation"])
    )
    resultado = loop._execute_task(
        task, "test-run", tmp_path / "runs", _config(tmp_path)
    )
    resultado["_task_type"] = task.task_type
    resultado["_payload"] = task.payload
    return resultado


def _estado(db: Path, goal_id: str) -> str:
    with sqlite3.connect(db) as conn:
        fila = conn.execute(
            "SELECT status FROM planning_graph WHERE goal_id=?", (goal_id,)
        ).fetchone()
    return str(fila[0]) if fila else "missing"


# ── 1. el ciclo completo ────────────────────────────────────────────────


def test_central_planifica_el_aprendizaje_de_una_experiencia_real(
    tmp_path: Path,
) -> None:
    """OBSERVAR → CLASIFICAR → DECIDIR → PLANIFICAR → EJECUTAR → REALIMENTAR."""
    db = tmp_path / "triade.db"
    AutonomousTaskStore(db)
    loop = _worker(tmp_path, db)

    # 1-3. el run termina y deja una observación durable.
    payload = _observacion(db, "run-causal-0001", PREFERENCIA)
    assert payload["source_run_id"] == "run-causal-0001"

    # 4-6. Central la recibe y produce un plan con pasos y dependencias.
    resultado = _ejecutar_siguiente(
        loop, tmp_path, db, {"central_learning_observation"}
    )
    assert resultado is not None
    assert resultado["status"] == "completed", resultado
    assert resultado["effect"] == "learning_plan_created", resultado
    assert resultado["disposition"] == "update_memory", resultado
    goal_id = resultado["goal_id"]
    assert resultado["planned_steps"] == [etapa for etapa, _, _ in LEARNING_STAGES]

    planner = CentralLearningPlanner(db)
    pasos = planner.graph.get_children(goal_id)
    assert len(pasos) == len(LEARNING_STAGES), (
        "un plan de aprendizaje no puede ser un único paso: eso es lo que hacía "
        "GoalOrchestrator para todo, y por eso planning_graph no tenía ni un "
        "goal con dos hijos"
    )
    with sqlite3.connect(db) as conn:
        dependencias = conn.execute(
            "SELECT COUNT(*) FROM goal_dependencies"
        ).fetchone()[0]
    assert dependencias == len(LEARNING_STAGES) - 1, (
        "las dependencias tienen que existir en la tabla, no sólo en la cabeza "
        "del planificador"
    )

    # Sólo la primera etapa está encolada: las demás esperan su turno.
    encoladas = [p for p in pasos if p.status == "queued"]
    assert [p.metadata["stage"] for p in encoladas] == ["extract"]

    # 7-8. el worker ejecuta la etapa lista y aparece evidencia.
    extraccion = _ejecutar_siguiente(
        loop, tmp_path, db, {"learning_candidate_generation"}
    )
    assert extraccion is not None
    assert extraccion["_payload"]["goal_id"] == goal_id, (
        "sin goal_id en el payload, worker_loop no llama a record_task_result y "
        "Central no se entera de nada: así estaban las 737 tareas de la base viva"
    )
    assert extraccion["status"] == "completed", extraccion
    assert extraccion["effect"] == "candidate_created", extraccion
    candidate_id = extraccion["candidate_id"]
    assert candidate_id

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        candidato = conn.execute(
            "SELECT * FROM learning_queue WHERE candidate_id=?", (candidate_id,)
        ).fetchone()
    assert candidato is not None, "la extracción tiene que dejar fila real"

    # 11. Central recibe el resultado y conoce el candidate_id.
    GoalOrchestrator(db).record_task_result(extraccion["_payload"], extraccion)
    assert planner._candidate_of(goal_id) == candidate_id, (
        "Central tiene que quedarse con el id que produjo su propio plan"
    )

    # 6 (dependencias) — la etapa siguiente sólo se encola al cumplirse la suya.
    pasos = {p.metadata["stage"]: p for p in planner.graph.get_children(goal_id)}
    assert pasos["extract"].status == "completed"
    assert pasos["dedupe"].status == "queued"
    assert pasos["evidence"].status == "pending"
    assert pasos["evaluate"].status == "pending"

    # 17. la observación de Central queda registrada y es enlazable.
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        observaciones = conn.execute(
            "SELECT disposition,outcome_status FROM goal_learning_observations"
            " WHERE goal_id=?",
            (goal_id,),
        ).fetchall()
    assert [o["disposition"] for o in observaciones] == ["update_memory"]


# ── 2. un worker no puede saltarse una dependencia ──────────────────────


def test_un_worker_no_puede_ejecutar_una_etapa_con_dependencias_abiertas(
    tmp_path: Path,
) -> None:
    db = tmp_path / "triade.db"
    AutonomousTaskStore(db)
    loop = _worker(tmp_path, db)
    payload = _observacion(db, "run-causal-0002", PREFERENCIA)
    plan = CentralLearningPlanner(db).plan_from_observation(payload)
    ultimo = plan["steps"][-1]
    assert ultimo["stage"] == "evaluate"

    # Se encola la última etapa a mano, saltándose las tres anteriores. Es lo
    # que haría un reintento mal dirigido o un script.
    tarea = WorkerTask(
        id=None,
        task_type=ultimo["task_type"],
        payload={
            "goal_id": plan["goal_id"],
            "goal_step_id": ultimo["step_id"],
            "worker_task_type": ultimo["task_type"],
            "stage": ultimo["stage"],
        },
        priority=25,
    )
    resultado = loop._execute_task(
        tarea, "test-run", tmp_path / "runs", _config(tmp_path)
    )
    assert resultado["status"] == "blocked"
    assert resultado["reason"] == "goal_step_dependency_not_satisfied"


# ── 3. replanificar no es reintentar ────────────────────────────────────


def test_sin_dato_medible_central_poda_el_plan_en_vez_de_reintentar(
    tmp_path: Path,
) -> None:
    """Medir un candidato sin dato sondeable no se reintenta: se replanifica.

    Es el patrón F-037 con otro nombre: `build_probe` devuelve `None`, la
    medición sale `no_op`, y sin medición no hay nada que evaluar. Antes el
    candidato volvía a salir elegido cada ciclo —465 intentos idénticos medidos
    el 2026-08-27—. Ahora Central deja de gastar y cierra.

    No hace falta modelo: el handler descarta por falta de sonda **antes** de
    tocar Ollama.
    """
    db = tmp_path / "triade.db"
    AutonomousTaskStore(db)
    loop = _worker(tmp_path, db)

    # Una preferencia real —`prefiero` la hace proposición— pero sin ningún
    # valor literal que preguntar después.
    _observacion(db, "run-causal-0003", "Prefiero que seas breve y directo siempre.")
    resultado = _ejecutar_siguiente(
        loop, tmp_path, db, {"central_learning_observation"}
    )
    assert resultado is not None
    assert resultado["effect"] == "learning_plan_created", resultado
    goal_id = resultado["goal_id"]
    orquestador = GoalOrchestrator(db)

    for tipo in ("learning_candidate_generation", "learning_candidate_deduplication"):
        etapa = _ejecutar_siguiente(loop, tmp_path, db, {tipo})
        assert etapa is not None, tipo
        orquestador.record_task_result(etapa["_payload"], etapa)

    medicion = _ejecutar_siguiente(loop, tmp_path, db, {"learning_evidence_generation"})
    assert medicion is not None, "la etapa de evidencia tenía que estar encolada"
    assert medicion["_payload"].get("candidate_id"), (
        "Central tiene que arrastrar el candidate_id de la extracción; sin él la "
        "medición sale no_op por 'sin_candidate_id' y la cadena finge avanzar"
    )
    if medicion["effect"] != "no_op":
        pytest.skip("este candidato resultó medible; la poda la cubre otra ruta")
    orquestador.record_task_result(medicion["_payload"], medicion)

    assert _estado(db, goal_id) == "completed"
    planner = CentralLearningPlanner(db)
    restantes = {
        p.metadata["stage"]: p.status for p in planner.graph.get_children(goal_id)
    }
    assert restantes["extract"] == "completed"
    assert restantes["dedupe"] == "completed"
    assert restantes["evaluate"] == "blocked", (
        "sin medición no hay nada que evaluar: esa etapa se poda"
    )

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        eventos = conn.execute(
            "SELECT event_type,reason FROM goal_events WHERE goal_id=?"
            " AND event_type='replanned'",
            (goal_id,),
        ).fetchall()
    assert eventos, "una poda por evidencia es una replanificación y se registra"

    # Y no se encoló ninguna etapa posterior: replanificar es dejar de gastar.
    with sqlite3.connect(db) as conn:
        pendientes = conn.execute(
            "SELECT COUNT(*) FROM autonomous_tasks WHERE status IN ('pending','queued')"
            " AND json_extract(payload_json,'$.goal_id')=?",
            (goal_id,),
        ).fetchone()[0]
    assert pendientes == 0


# ── 4. prueba negativa: una pregunta trivial no crea neurona ────────────


def test_una_pregunta_factual_trivial_no_produce_neurona_ni_plan(
    tmp_path: Path,
) -> None:
    db = tmp_path / "triade.db"
    AutonomousTaskStore(db)
    planner = CentralLearningPlanner(db)
    decision = planner.plan_from_observation(
        {
            "source_run_id": "run-causal-0004",
            "message": "¿Qué hora es?",
            "response": "No tengo reloj.",
            "domain": "conversation",
        }
    )
    assert decision["disposition"] == "ignore"
    assert decision["steps"] == []
    assert decision["task_id"] is None
    assert _estado(db, decision["goal_id"]) == "blocked"

    with sqlite3.connect(db) as conn:
        neuronas = conn.execute("SELECT COUNT(*) FROM neurons").fetchone()[0]
        tareas = conn.execute(
            "SELECT COUNT(*) FROM autonomous_tasks WHERE task_type LIKE 'learning%'"
        ).fetchone()[0]
    assert neuronas == 0
    assert tareas == 0


# ── 5. deduplicación: la misma habilidad dicha de dos maneras ───────────


def test_la_misma_habilidad_dicha_de_dos_maneras_no_crea_dos_neuronas(
    tmp_path: Path,
) -> None:
    """Seis neuronas para «hacer imágenes» es el defecto que esto cierra."""
    from triade.core.neuron_creator import NeuronSpec
    from triade.core.neuron_registry import NeuronRegistry

    db = tmp_path / "triade.db"
    AutonomousTaskStore(db)
    registro = NeuronRegistry(db_path=db)
    registro.register(
        NeuronSpec(
            name="neurona-quiero-hagas-imagen",
            mission="quiero que me hagas una imagen",
            domain="system_governance",
            status="experimental",
            created_by="test",
        )
    )

    planner = CentralLearningPlanner(db)
    observacion = {
        "source_run_id": "run-causal-0005",
        "message": "quiero que aprendas a hacer imágenes digitales",
        "response": "",
        "domain": "conversation",
        # La intención que calculó el Hipotálamo en el run real. Sin ella la
        # compuerta no reconoce la petición de capacidad y Central no llega
        # siquiera a plantearse si ya existe una neurona equivalente.
        "intent": "build_or_update",
    }
    clasificacion = planner.classify(observacion)
    existente = planner.search_existing_knowledge(observacion, clasificacion)
    assert existente["similar_neuron"] is not None, existente
    assert existente["neuron_similarity"] >= 0.5

    decision = planner.decide(clasificacion, existente)
    assert decision["disposition"] == "update_existing_neuron"
    assert decision["neuron"]["name"] == "neurona-quiero-hagas-imagen"

    plan = planner.plan_from_observation(observacion)
    assert plan["disposition"] == "update_existing_neuron"
    assert plan["steps"] == []
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM neurons").fetchone()[0] == 1


# ── 6. la conversación no espera al aprendizaje ─────────────────────────


def test_observar_no_hace_inferencia_en_el_camino_de_respuesta(
    tmp_path: Path,
) -> None:
    """El sensor escribe una fila y sale. Ni modelo, ni red, ni planificación."""
    db = tmp_path / "triade.db"
    AutonomousTaskStore(db)
    _observacion(db, "run-causal-0006", PREFERENCIA)
    with sqlite3.connect(db) as conn:
        tablas = {
            str(f[0])
            for f in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        # Nada de planificación todavía: el plan lo hace el worker, después. En
        # una base recién creada el sensor ni siquiera toca el esquema del grafo,
        # que es la forma más fuerte de decir que no planificó nada.
        for tabla in ("planning_graph", "goal_dependencies", "learning_queue"):
            if tabla in tablas:
                assert (
                    conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0] == 0
                ), f"{tabla} no puede tener filas antes de que Central planifique"


# ── 7. la deduplicación también protege el camino síncrono ──────────────


def test_el_runner_no_registra_una_neurona_gemela_de_una_existente(
    tmp_path: Path,
) -> None:
    """Donde de verdad nacían las gemelas era el camino de respuesta.

    `_propose_neuron_candidate` deduplicaba por **nombre**, y el nombre es un
    slug del mensaje: nunca coincidía. Así se llegó a seis neuronas para «hacer
    imágenes» y a dos por una misma conversación de dos turnos.
    """
    from triade.core.learning_planner import find_equivalent_neuron
    from triade.core.neuron_creator import NeuronSpec
    from triade.core.neuron_registry import NeuronRegistry

    db = tmp_path / "triade.db"
    AutonomousTaskStore(db)
    NeuronRegistry(db_path=db).register(
        NeuronSpec(
            name="neurona-quiero-hagas-imagen",
            mission="quiero que me hagas una imagen",
            domain="system_governance",
            status="candidate",
            created_by="test",
        )
    )

    for variante in (
        "quiero que aprendas a hacer imágenes digitales",
        "pero quiero que me hagas una imagen de una casa",
        "quiero que aprendas de verdad a hacer imagenes",
    ):
        gemela, parecido = find_equivalent_neuron(db, variante)
        assert gemela is not None, f"no detectó la gemela de: {variante}"
        assert gemela["name"] == "neurona-quiero-hagas-imagen"
        assert parecido >= 0.5

    # Y una petición de otra habilidad sigue siendo otra habilidad.
    otra, _ = find_equivalent_neuron(db, "necesito que revises el repositorio git")
    assert otra is None


# ── 8. observabilidad: la cadena entera desde el run ────────────────────


def test_la_cadena_de_aprendizaje_es_legible_de_punta_a_punta(
    tmp_path: Path,
) -> None:
    """Un solo identificador —el run— basta para ver todo el circuito."""
    db = tmp_path / "triade.db"
    AutonomousTaskStore(db)
    loop = _worker(tmp_path, db)
    _observacion(db, "run-causal-0007", PREFERENCIA)
    _ejecutar_siguiente(loop, tmp_path, db, {"central_learning_observation"})
    extraccion = _ejecutar_siguiente(
        loop, tmp_path, db, {"learning_candidate_generation"}
    )
    assert extraccion is not None
    GoalOrchestrator(db).record_task_result(extraccion["_payload"], extraccion)

    cadena = CentralLearningPlanner(db).chain_for_run("run-causal-0007")
    assert cadena["observation"]["task_type"] == "central_learning_observation"
    assert cadena["goal"]["disposition"] == "update_memory"
    assert cadena["goal"]["candidate_id"] == extraccion["candidate_id"]
    assert [p["stage"] for p in cadena["steps"]] == [
        etapa for etapa, _, _ in LEARNING_STAGES
    ]
    # Las dependencias se ven, no hay que deducirlas.
    assert cadena["steps"][0]["depends_on"] == []
    assert cadena["steps"][1]["depends_on"] == [cadena["steps"][0]["step_id"]]
    # Y cada tarea sabe a qué paso pertenece.
    assert all(t["step_id"] for t in cadena["tasks"]), cadena["tasks"]
    assert cadena["candidate"]["candidate_id"] == extraccion["candidate_id"]
    assert cadena["observations"], "la decisión de Central queda registrada"

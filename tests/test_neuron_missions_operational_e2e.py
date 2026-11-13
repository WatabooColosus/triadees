"""E2E mínimo de operación neuronal real."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.core.neuron_creator import NeuronSpec
from triade.core.neuron_missions import NeuronEvidence, NeuronMissionStore
from triade.core.neuron_registry import NeuronRegistry
from triade.workers.contracts import WorkerRunConfig, WorkerTask
from triade.workers.mission_planner import MissionPlanner
from triade.workers.neuron_mission_backfill import (
    backfill_neuron_missions,
    neuron_missions_doctor,
)
from triade.workers.worker_loop import WorkerLoop


def make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
    return db_path


def create_experimental_neuron(db_path: Path) -> dict:
    registry = NeuronRegistry(db_path=db_path)
    spec = NeuronSpec(
        name="e2e-neuron",
        mission="Seguir misiones neuronales con evidencia auditable local.",
        domain="observability",
        rules=["rule-1", "rule-2", "rule-3", "rule-4", "rule-5"],
        triggers=["run"],
        inputs_allowed=["runs"],
        outputs_allowed=["diagnosis"],
        forbidden_actions=[
            "write_stable_memory",
            "modify_identity_core",
            "shell",
            "network",
        ],
        success_metrics=["cycles", "evidence"],
        evidence_required=["run", "worker"],
        status="experimental",
        created_by="tests",
    )
    registry.register(spec)
    registry.update_status(spec.name, "experimental")
    return registry.get_neuron(spec.name)


def test_operational_neuron_mission_flow(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    neuron = create_experimental_neuron(db_path)
    with sqlite3.connect(db_path) as conn:
        identity_before = conn.execute(
            "SELECT key, value, category, confidence FROM identity_core ORDER BY id"
        ).fetchall()

    backfill = backfill_neuron_missions(
        db_path=db_path, runs_dir=tmp_path / "runs", limit=20
    )
    assert backfill["created_count"] == 1
    mission_id = int(backfill["created"][0]["id"])
    NeuronMissionStore(db_path=db_path).record_evidence(
        NeuronEvidence(
            mission_id=mission_id,
            neuron_id=int(neuron["id"]),
            evidence_type="user_run",
            source="user_run",
            content="Evidencia E2E",
            refs=["run:user-e2e"],
            score=0.8,
        )
    )

    planner = MissionPlanner(db_path=db_path)
    planned = planner.plan_cycle()
    task = next(t for t in planned if t.task_type == "experimental_neuron_activity")
    assert task.payload["mission_id"]

    loop = WorkerLoop(db_path=db_path, runs_dir=tmp_path / "runs")
    result = loop._experimental_neuron_activity(
        WorkerTask(
            task_type="experimental_neuron_activity", payload=task.payload, id=1
        ),
        run_ref="run-e2e-1",
        task_dir=tmp_path / "task",
        config=WorkerRunConfig(task_timeout=10),
    )

    assert result["stable_memory_written"] is False
    assert result["cycle_id"] > 0
    assert result["evidence_id"] > 0
    assert result["score_id"] > 0
    assert result["learning_candidate"] is not None
    assert result["decision"] == "learning_candidate_proposed"

    mission_id = int(task.payload["mission_id"])
    with sqlite3.connect(db_path) as conn:
        cycles = conn.execute(
            "SELECT COUNT(*) FROM neuron_work_cycles WHERE mission_id = ?",
            (mission_id,),
        ).fetchone()[0]
        evidence = conn.execute(
            "SELECT COUNT(*) FROM neuron_evidence WHERE mission_id = ?", (mission_id,)
        ).fetchone()[0]
        scores = conn.execute(
            "SELECT COUNT(*) FROM neuron_scores WHERE mission_id = ?", (mission_id,)
        ).fetchone()[0]
        learning = conn.execute(
            "SELECT COUNT(*) FROM learning_queue WHERE source_ref = ?",
            (f"mission:{mission_id}:run:run-e2e-1",),
        ).fetchone()[0]

    doctor = neuron_missions_doctor(
        db_path=db_path, runs_dir=tmp_path / "runs", limit=20
    )
    with sqlite3.connect(db_path) as conn:
        identity_after = conn.execute(
            "SELECT key, value, category, confidence FROM identity_core ORDER BY id"
        ).fetchall()

    assert cycles >= 1
    assert evidence >= 1
    assert scores >= 1
    assert learning >= 1
    assert doctor["total_missions"] >= 1
    assert doctor["mission_learning_candidates"] >= 1
    assert identity_after == identity_before


def test_la_hipotesis_de_mision_se_enuncia_una_vez_no_cada_ciclo(tmp_path) -> None:
    """Repetir la misma frase cada ciclo es ruido con forma de aprendizaje.

    El texto se compone de `title` y `mission` —constantes de la misión—, así
    que a partir del segundo ciclo no aporta nada. Medido el 2026-08-08 sobre la
    base viva: 233 candidatos de esta plantilla con 11 contenidos distintos, uno
    repetido 104 veces, y eran los que más «usos» acumulaban (44). El
    aprendizaje más usado del sistema era el más repetido, no el más aprendido.
    """
    from triade.workers.neuron_mission_executor import NeuronMissionExecutor

    ejecutor = NeuronMissionExecutor(db_path=tmp_path / "triade.db")
    base = {
        "mission": {
            "id": 1,
            "title": "Misión de prueba",
            "domain": "general",
            "mission": "hacer algo medible",
        },
        "allowed_actions": ["observe", "propose_learning"],
        "allowed_sources": ["run"],
        "run_ref": "r1",
        "recent_evidence": [],
        "latest_score": {},
    }

    primero = ejecutor._run_local_cycle({**base, "recent_cycles": []})
    segundo = ejecutor._run_local_cycle({**base, "recent_cycles": [{"id": 1}]})

    assert primero["proposed_learning"], "el primer ciclo sí enuncia la hipótesis"
    assert not segundo["proposed_learning"], (
        "un ciclo posterior volvió a emitir la misma frase: eso inunda "
        "learning_queue con copias que no aportan nada"
    )

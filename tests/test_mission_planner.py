"""Tests del MissionPlanner."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.core.error_bus import query_internal_errors
from triade.core.neuron_missions import (
    NeuronEvidence,
    NeuronMission,
    NeuronMissionStore,
)
from triade.learning.evidence_bridge import LearningEvidenceBridge
from triade.memory.semantic_store import SemanticMemoryStore
from triade.workers.mission_planner import MissionPlanner, PlannedTask


def make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
    return db_path


def test_planned_task_to_dict() -> None:
    task = PlannedTask(
        task_type="pending_learning_review",
        priority=20,
        reason="Test reason",
        source="test",
        related_neuron_id=5,
        related_candidate_id=10,
        payload={"key": "value"},
    )
    d = task.to_dict()
    assert d["task_type"] == "pending_learning_review"
    assert d["priority"] == 20
    assert d["reason"] == "Test reason"
    assert "planner_score" in d
    assert d["related_neuron_id"] == 5
    assert d["related_candidate_id"] == 10
    assert d["payload"]["key"] == "value"


def test_plan_empty_db_returns_minimal_tasks(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    planner = MissionPlanner(db_path=db_path)
    tasks = planner.plan_cycle()
    assert isinstance(tasks, list)
    assert all(isinstance(t, PlannedTask) for t in tasks)
    assert [t.task_type for t in tasks] == ["pulse_check"]
    assert all(t.reason and t.source and t.planner_score >= 0 for t in tasks)


def test_plan_pending_learning(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO learning_queue
            (candidate_id, title, content, source_type, risk_level, confidence, status, domain, source_ref, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "cand-001",
                "Test candidate",
                "content here",
                "conversation",
                "low",
                0.8,
                "candidate",
                "test",
                "run:001",
                "2026-01-01",
            ),
        )
    planner = MissionPlanner(db_path=db_path)
    tasks = planner.plan_cycle()
    learning_tasks = [t for t in tasks if t.task_type == "pending_learning_review"]
    assert len(learning_tasks) >= 1
    reasons = [t.reason for t in learning_tasks]
    assert any("Test candidate" in r for r in reasons)


def test_plan_priority_ordering(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        for i in range(3):
            conn.execute(
                """INSERT INTO learning_queue
                (candidate_id, title, content, source_type, risk_level, confidence, status, domain, source_ref, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"cand-{i:03d}",
                    f"Cand {i}",
                    "content",
                    "conversation",
                    "low",
                    0.9 - i * 0.1,
                    "candidate",
                    "test",
                    "run:001",
                    "2026-01-01",
                ),
            )
    planner = MissionPlanner(db_path=db_path)
    tasks = planner.plan_cycle()
    priorities = [t.priority for t in tasks]
    assert priorities == sorted(priorities)


def test_plan_active_missions(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    store = NeuronMissionStore(db_path=db_path)
    mission_id = store.create_mission(
        NeuronMission(
            neuron_id=1,
            title="Active mission",
            mission="Test",
            domain="test",
            status="experimental",
        )
    )
    store.record_evidence(
        NeuronEvidence(
            mission_id=mission_id,
            neuron_id=1,
            evidence_type="user_run",
            source="user_run",
            content="Evidencia nueva",
            refs=["run:user"],
            score=0.8,
        )
    )
    planner = MissionPlanner(db_path=db_path)
    tasks = planner.plan_cycle()
    mission_tasks = [t for t in tasks if t.task_type == "experimental_neuron_activity"]
    assert len(mission_tasks) >= 1
    assert mission_tasks[0].related_neuron_id == 1


def test_plan_system_debt(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        for i in range(10):
            conn.execute(
                "INSERT INTO runs (run_id, source, user_input, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (f"run-{i:03d}", "react-ui", "input", "ok", "2026-01-01"),
            )
    planner = MissionPlanner(db_path=db_path)
    tasks = planner.plan_cycle()
    debt_tasks = [t for t in tasks if t.task_type == "system_debt_scan"]
    assert len(debt_tasks) >= 1


def test_plan_respects_limit(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        for i in range(20):
            conn.execute(
                """INSERT INTO learning_queue
                (candidate_id, title, content, source_type, risk_level, confidence, status, domain, source_ref, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"cand-limit-{i:03d}",
                    f"Cand {i}",
                    "content",
                    "conversation",
                    "low",
                    0.5,
                    "candidate",
                    "test",
                    "run:001",
                    "2026-01-01",
                ),
            )
    planner = MissionPlanner(db_path=db_path)
    tasks = planner.plan_cycle()
    assert len(tasks) <= 15


def test_plan_records_internal_error_when_query_fails(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE learning_queue")

    planner = MissionPlanner(db_path=db_path)
    tasks = planner.plan_cycle()

    assert any(t.task_type == "pulse_check" for t in tasks)
    errors = query_internal_errors(scope="mission_planner.baseline", db_path=db_path)
    assert errors
    assert errors[0]["payload"]["context"]["operation"] == "baseline_sql_queries"


def test_semantic_governance_is_planned_from_the_live_store(tmp_path: Path) -> None:
    """La compuerta debe mirar donde la ingesta escribe de verdad.

    El almacén semántico vivo es `semantic_documents`: ahí escribe
    `SemanticMemoryStore` y sobre esos documentos actúa
    `SemanticMemoryGovernance`. La tabla `semantic_memory` quedó atrás y en
    producción lleva 0 filas frente a 186 documentos `candidate`. Mientras la
    condición consulte la tabla retirada, `semantic_memory_governance` no se
    encola nunca: 0 ejecuciones en 4 777 tareas.
    """
    db_path = make_db(tmp_path)
    # `schemas.sql` no declara `learning_evidence` ni `semantic_documents`: las
    # crean sus propios módulos al inicializarse. Sin ellas el bloque baseline
    # aborta en la consulta anterior y nunca llega a la compuerta semántica, que
    # es justo lo que este test tiene que ejercitar.
    LearningEvidenceBridge(db_path=db_path)
    store = SemanticMemoryStore(db_path=db_path)
    store.upsert_document(
        content="Los grafos internos se generan desde el AST, no desde la documentación.",
        domain="observabilidad",
        source_type="manual",
        source_ref="tests/test_mission_planner.py",
    )
    with sqlite3.connect(db_path) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            ("semantic_memory",),
        ).fetchone()
        assert (
            conn.execute("SELECT COUNT(*) FROM semantic_documents").fetchone()[0] == 1
        )

    tasks = MissionPlanner(db_path=db_path).plan_cycle()

    governance = [t for t in tasks if t.task_type == "semantic_memory_governance"]
    assert governance, "un documento candidate debe encolar la gobernanza semántica"
    assert "1" in governance[0].reason


def test_todo_tipo_con_cadencia_declarada_tiene_productor(tmp_path) -> None:
    """Una cadencia declarada sin productor es una tarea que no corre jamás.

    `AdaptiveScheduler.DEFAULT_INTERVALS` distingue las dos naturalezas: los
    tipos bajo demanda llevan `0.0` —los produce `GoalOrchestrator` tras una
    petición— y los periódicos llevan su intervalo. Un tipo con intervalo > 0 y
    sin nadie que lo planifique sólo podía encolarse por `enqueue_defaults()`,
    que es el fallback de `schedule_cycle` y no corre nunca porque
    `plan_cycle()` no devuelve vacío.

    Así estuvo `bodega_global_review`: handler, política de concurrencia y
    `TASK_PRODUCERS: MissionPlanner`, todo declarado, y cero ejecuciones.
    """
    from triade.workers.adaptive_scheduler import AdaptiveScheduler
    from triade.workers.architecture import TASK_PRODUCERS

    periodicos = {
        tipo
        for tipo, intervalo in AdaptiveScheduler.DEFAULT_INTERVALS.items()
        if intervalo > 0 and TASK_PRODUCERS.get(tipo) == "MissionPlanner"
    }
    raiz = Path(__file__).resolve().parents[1]
    fuente = (raiz / "triade/workers/mission_planner.py").read_text(encoding="utf-8")

    sin_productor = sorted(t for t in periodicos if f'task_type="{t}"' not in fuente)

    assert not sin_productor, (
        "tipos con cadencia declarada que MissionPlanner nunca planifica, "
        f"así que sólo podrían llegar por el fallback: {sin_productor}"
    )

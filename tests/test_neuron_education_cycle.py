from __future__ import annotations

import sqlite3

from triade.neurons import NeuronEducationCycle
from triade.neurons.competency_store import CompetencyStore
from triade.workers.mission_planner import MissionPlanner
from triade.workers.state_store import WorkerStateStore


def _database(tmp_path):
    path = tmp_path / "education.db"
    WorkerStateStore(path)
    with sqlite3.connect(path) as conn:
        neuron_id = conn.execute(
            """INSERT INTO neurons(name,mission,domain,rules,triggers,inputs_allowed,outputs_allowed,
            forbidden_actions,success_metrics,evidence_required,activation_policy,contract_json,status,created_by)
            VALUES('Código','reparar código con pruebas','code_repair','[]','[]','[]','[]','[]','[]','[]','{}','{}','experimental','test')"""
        ).lastrowid
        conn.execute(
            """INSERT INTO neuron_missions(neuron_id,title,mission,domain,allowed_sources_json,allowed_actions_json,status)
            VALUES(?,?,?,?,?,?,?)""",
            (neuron_id, "Código", "reparar código con pruebas", "code_repair", '["repo","document","web"]', '["observe"]', "experimental"),
        )
    return path, int(neuron_id)


def _material(path, source_ref, title, content):
    with sqlite3.connect(path) as conn:
        conn.execute(
            """INSERT INTO learning_queue(candidate_id,source_type,source_ref,title,content,normalized_summary,
            domain,risk_level,confidence,utility,status,verification_notes,created_at,updated_at)
            VALUES(?, 'web', ?, ?, ?, ?, 'code_repair', 'low', .8, .8, 'cross_checked', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (f"candidate-{title}", source_ref, title, content, content),
        )


def test_cycle_refuses_to_claim_learning_without_independent_material(tmp_path):
    path, _ = _database(tmp_path)
    result = NeuronEducationCycle(path).run_once()
    assert result["status"] == "needs_research"
    assert result["learned"] is False
    assert result["independent_sources"] == 0
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT state FROM neuron_education_sessions").fetchone()[0] == "material_insufficient"


def test_cycle_prepares_lesson_but_does_not_self_approve(tmp_path):
    path, _ = _database(tmp_path)
    _material(path, "https://docs.python.org/testing", "Pruebas de código", "reparar código requiere pruebas reproducibles")
    _material(path, "https://sqlite.org/testing.html", "Validación independiente", "código reparado debe superar pruebas y validación")
    result = NeuronEducationCycle(path).run_once()
    assert result["status"] == "lesson_prepared"
    assert result["learned"] is False
    assert result["independent_sources"] == 2
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT state,evaluation_json FROM neuron_education_sessions").fetchone()
    assert row[0] == "lesson_prepared"
    assert "run_application_pending" in row[1]


def test_planner_schedules_due_education(tmp_path):
    path, _ = _database(tmp_path)
    CompetencyStore(path)
    planned = MissionPlanner(path).plan_cycle()
    assert "neuron_education_cycle" in {task.task_type for task in planned}

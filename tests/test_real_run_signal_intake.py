"""Real UI mission signals: temporary SQLite, no synthetic production learning."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from triade.core.neuron_missions import NeuronMission, NeuronMissionStore
from triade.neurons.real_run_signal_intake import RealRunSignalIntake
from triade.workers.mission_planner import MissionPlanner


@pytest.fixture
def db(tmp_path: Path) -> Path:
    db_path = tmp_path / "neuron-run-test.sqlite3"
    store = NeuronMissionStore(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO neurons "
            "(name,mission,domain,status,rules,triggers,inputs_allowed,outputs_allowed,"
            "forbidden_actions,success_metrics,evidence_required,activation_policy,"
            "contract_json,created_at) "
            "VALUES ('security-neuron','analizar seguridad','security','stable',"
            "'[]','[]','[]','[]','[]','[]','[]','{}','{}',?)",
            (datetime.now(UTC).isoformat(),),
        )
    store.create_mission(
        NeuronMission(
            neuron_id=1,
            title="Auditoría de seguridad",
            mission="Analizar seguridad del sistema con pruebas verificables",
            domain="security",
            status="stable",
            allowed_sources=["run", "worker"],
        )
    )
    return db_path


def _run(
    db_path: Path,
    *,
    run_id: str = "ui-run-123",
    source: str = "react-ui",
    status: str = "ok",
    text: str = "Necesito analizar la seguridad de la aplicación",
    when: datetime | None = None,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs (run_id,source,user_input,status,created_at) "
            "VALUES(?,?,?,?,?)",
            (
                run_id,
                source,
                text,
                status,
                (when or datetime.now(UTC)).isoformat(),
            ),
        )


def _evidence(db_path: Path) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT mission_id,evidence_type,source,content,refs_json,score "
            "FROM neuron_evidence ORDER BY id"
        ).fetchall()


def test_completed_relevant_human_run_creates_only_nonlearning_signal(db: Path):
    _run(db)
    result = RealRunSignalIntake(db).harvest()
    assert result["status"] == "signals_recorded"
    assert result["created"] == 1
    assert result["fact_verified"] is False
    assert result["learning_applied"] is False
    rows = _evidence(db)
    assert len(rows) == 1
    assert rows[0][1:3] == ("human_run_signal", "run")
    assert "seguridad de la aplicación" not in rows[0][3]
    assert json.loads(rows[0][4]) == ["run:ui-run-123"]
    assert rows[0][5] == 0.0
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM neuron_education_applications"
        ).fetchone()[0] == 0


@pytest.mark.parametrize(
    "source,status,text",
    [
        ("worker", "ok", "analizar seguridad del sistema"),
        ("react-ui", "created", "analizar seguridad del sistema"),
        ("react-ui", "ok", "hola gracias"),
        ("system_pulse_continuous", "ok", "analizar seguridad del sistema"),
    ],
)
def test_worker_unverified_or_irrelevant_run_is_never_an_external_signal(
    db: Path, source: str, status: str, text: str
):
    _run(db, source=source, status=status, text=text)
    assert RealRunSignalIntake(db).harvest()["created"] == 0
    assert _evidence(db) == []


def test_duplicate_human_run_never_multiplies_evidence(db: Path):
    _run(db)
    reader = RealRunSignalIntake(db)
    assert reader.harvest()["created"] == 1
    assert reader.harvest()["created"] == 0
    assert len(_evidence(db)) == 1


def test_stale_human_run_older_than_completed_mission_cycle_is_skipped(db: Path):
    _run(db, when=datetime.now(UTC) - timedelta(minutes=30))
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO neuron_work_cycles (mission_id,neuron_id,cycle_type,status,"
            "created_at) VALUES(1,1,'mission_work','completed',?)",
            (datetime.now(UTC).isoformat(),),
        )
    assert RealRunSignalIntake(db).harvest()["created"] == 0


def test_old_human_run_is_not_replayed_on_restart(db: Path):
    _run(db, when=datetime.now(UTC) - timedelta(days=3))
    assert RealRunSignalIntake(db).harvest()["created"] == 0


def test_mission_disallowed_to_read_runs_is_not_awakened(db: Path):
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE neuron_missions SET allowed_sources_json='[\"worker\"]'"
        )
    _run(db)
    assert RealRunSignalIntake(db).harvest()["created"] == 0


def test_mission_planner_uses_real_signal_without_learning(db: Path):
    _run(db)
    tasks = MissionPlanner(db)._plan_active_missions()
    assert any(
        t.task_type == "experimental_neuron_activity"
        and t.source == "mission_planner_mission"
        and t.payload.get("evidence_origin") == "run"
        and "run:ui-run-123" in t.payload.get("evidence_refs", [])
        for t in tasks
    )
    assert len(_evidence(db)) == 1
    # Repeating a scheduler tick is idempotent, even if it reuses pending task.
    MissionPlanner(db)._plan_active_missions()
    assert len(_evidence(db)) == 1


def test_planner_does_not_hide_stable_missions_after_first_five(db: Path):
    store = NeuronMissionStore(db)
    # Existing stable mission #1 is unrelated to the incoming human signal.
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE neuron_missions SET allowed_sources_json='[\"worker\"]' WHERE id=1"
        )
    for number in range(2, 11):
        store.create_mission(
            NeuronMission(
                neuron_id=1,
                title=f"Misión auxiliar {number}",
                mission="Observar recursos auxiliares",
                status="stable",
                allowed_sources=["worker"] if number < 10 else ["run"],
            )
        )
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE neuron_missions SET title='Auditoría de seguridad',"
            "mission='Analizar seguridad del sistema' WHERE id=10"
        )
    _run(db)
    tasks = MissionPlanner(db)._plan_active_missions()
    assert any(t.payload.get("mission_id") == 10 for t in tasks)
    assert any(row[0] == 10 for row in _evidence(db))

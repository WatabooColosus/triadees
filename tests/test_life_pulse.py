"""Tests del pulso vital operativo."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from triade.core.life_pulse import LifePulseEngine
from triade.core.error_bus import query_internal_errors


def make_life_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
        run_id = "life-run-1"
        conn.execute(
            """INSERT INTO runs
            (run_id, source, user_input, status, model_hypothalamus, model_central, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_id, "test", "pulso vida aprendizaje segundo plano", "ok", "rules-fallback", "template-fallback", "2026-06-05"),
        )
        conn.execute(
            "INSERT INTO signal_states (run_id, intent, tone, urgency, risk, pv7, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, "conversation", "constructive", "medium", "low", "{}", "[]"),
        )
        conn.execute(
            "INSERT INTO crystal_states (run_id, q_crystal, stability, q_delta, stability_delta, temporal_status) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, 0.6, 0.8, 0.0, 0.0, "stable"),
        )
        conn.execute(
            "INSERT INTO verification_reports (run_id, status, warnings, recommendations) VALUES (?, ?, ?, ?)",
            (run_id, "ok", "[]", "[]"),
        )
        conn.execute(
            "INSERT INTO model_events (run_id, role, provider, model_name, ok, quality_score) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, "hypothalamus", "rules", "rules-fallback", 0, 0.75),
        )
        conn.execute(
            "INSERT INTO model_events (run_id, role, provider, model_name, ok, quality_score) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, "central", "template", "template-fallback", 0, 0.75),
        )
        conn.execute(
            "INSERT INTO episodic_memory (run_id, title, content, summary, tags) VALUES (?, ?, ?, ?, ?)",
            (run_id, "Pulso", "Usuario privado\nRespuesta", "Resumen", "triade,mvp,run"),
        )
    return db_path


def test_life_pulse_tick_counts_integrity_and_reflection(tmp_path: Path) -> None:
    db_path = make_life_db(tmp_path)
    engine = LifePulseEngine(db_path=db_path, runs_dir=tmp_path / "runs", interval_seconds=5, reflection_limit=10)

    payload = engine.tick()

    assert payload["status"] == "ok"
    assert payload["policy"]["background_learning"] == "candidate_detection_only"
    assert payload["policy"]["auto_consolidation"] is False
    assert payload["counters"]["cycles"] == 1
    assert payload["counters"]["integrity_checks"] == 1
    assert payload["integrity"]["ok"] is True
    assert payload["integrity"]["counts"]["runs"] == 1
    assert "neuron_proposals" in payload["reflection"]


def test_life_pulse_records_actions_without_db_write(tmp_path: Path) -> None:
    db_path = make_life_db(tmp_path)
    engine = LifePulseEngine(db_path=db_path, runs_dir=tmp_path / "runs", interval_seconds=5)

    engine.record_action("doctor")
    engine.record_action("doctor")
    payload = engine.snapshot()

    assert payload["actions"]["doctor"] == 2
    assert payload["counters"]["actions_observed"] == 2


def test_continuous_runner_records_controlled_error(tmp_path: Path) -> None:
    db_path = make_life_db(tmp_path)
    engine = LifePulseEngine(
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        continuous_run_enabled=True,
        continuous_interval_seconds=0,
        continuous_max_cycles=1,
        autonomy_level="form_candidates",
    )

    with patch("triade.core.background_neurons.candidates_from_system_debt", side_effect=RuntimeError("boom candidate formation")), \
            patch.object(engine._stop, "wait", return_value=True):
        engine._continuous_loop()

    errors = query_internal_errors(scope="life_pulse.continuous.candidate_formation", db_path=db_path)
    assert errors
    assert errors[0]["payload"]["context"]["operation"] == "candidates_from_system_debt_and_form_candidates"
    assert engine.snapshot()["continuous_runner"]["last_error"] == "boom candidate formation"

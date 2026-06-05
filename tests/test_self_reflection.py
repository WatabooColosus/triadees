"""Tests de reflexion interna del nucleo."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.core.self_reflection import SelfReflectionEngine


def make_reflection_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
        for index in range(4):
            run_id = f"reflect-run-{index}"
            conn.execute(
                """INSERT INTO runs
                (run_id, source, user_input, status, model_hypothalamus, model_central, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    "test",
                    "prueba nombre memoria cristal fallback",
                    "ok",
                    "rules-fallback",
                    "template-fallback",
                    "2026-06-05",
                ),
            )
            conn.execute(
                "INSERT INTO signal_states (run_id, intent, tone, urgency, risk, pv7, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, "conversation", "constructive", "medium", "low", "{}", "[]"),
            )
            conn.execute(
                """INSERT INTO crystal_states
                (run_id, q_crystal, stability, q_delta, stability_delta, temporal_status)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, 0.55, 0.8, -0.06 if index == 2 else 0.0, 0.0, "degrading" if index == 2 else "stable"),
            )
            conn.execute(
                """INSERT INTO verification_reports
                (run_id, status, warnings, recommendations)
                VALUES (?, ?, ?, ?)""",
                (run_id, "ok", '["fallback recurrente"]', "[]"),
            )
            conn.execute(
                """INSERT INTO model_events
                (run_id, role, provider, model_name, ok, quality_score)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, "hypothalamus", "rules", "rules-fallback", 0, 0.75),
            )
            conn.execute(
                """INSERT INTO model_events
                (run_id, role, provider, model_name, ok, quality_score)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, "central", "template", "template-fallback", 0, 0.75),
            )
            conn.execute(
                "INSERT INTO episodic_memory (run_id, title, content, summary, tags) VALUES (?, ?, ?, ?, ?)",
                (run_id, "Run", "Usuario privado\nRespuesta", "Resumen", "triade,mvp,run"),
            )
    return db_path


def test_self_reflection_proposes_neurons_without_writing_by_default(tmp_path: Path) -> None:
    db_path = make_reflection_db(tmp_path)
    before = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM neurons").fetchone()[0]

    payload = SelfReflectionEngine(db_path=db_path).reflect(limit=10)

    after = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM neurons").fetchone()[0]
    assert before == after
    assert payload["status"] == "ok"
    assert payload["policy"]["neuron_registration"] == "proposal_only"
    assert payload["policy"]["auto_learning_consolidation"] is False
    assert "neurona_diagnostico_modelos" in {item["name"] for item in payload["neuron_proposals"]}
    assert payload["self_improvement_loop"][0]["stage"] == "observe"


def test_self_reflection_can_register_candidate_neurons_explicitly(tmp_path: Path) -> None:
    db_path = make_reflection_db(tmp_path)

    payload = SelfReflectionEngine(db_path=db_path).reflect(limit=10, register_neuron_candidates=True)

    rows = sqlite3.connect(db_path).execute("SELECT name, status, created_by FROM neurons").fetchall()
    assert payload["policy"]["neuron_registration"] == "candidate_only"
    assert payload["registered_neuron_candidates"]
    assert rows
    assert {row[1] for row in rows} == {"candidate"}
    assert {row[2] for row in rows} == {"self_reflection"}


def test_self_reflection_exports_markdown(tmp_path: Path) -> None:
    db_path = make_reflection_db(tmp_path)
    engine = SelfReflectionEngine(db_path=db_path)
    payload = engine.reflect(limit=10)

    path = engine.export_markdown(payload, tmp_path / "SELF_IMPROVEMENT_PATH.md")

    text = path.read_text(encoding="utf-8")
    assert "Triade Self Improvement Path" in text
    assert "Neuronas Propuestas" in text
    assert "Decisiones Humanas Requeridas" in text

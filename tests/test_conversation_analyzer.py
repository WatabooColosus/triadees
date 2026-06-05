"""Tests del analizador seguro de conversaciones."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.core.conversation_analyzer import ConversationAnalyzer


def make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
        conn.execute(
            "INSERT OR IGNORE INTO identity_core (key, value, category, confidence) VALUES (?, ?, ?, ?)",
            ("entity_name", "Tríade Ω", "identity", 1.0),
        )
        for index in range(3):
            run_id = f"run-{index}"
            conn.execute(
                """INSERT INTO runs
                (run_id, source, user_input, status, model_hypothalamus, model_central, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    "test" if index < 2 else "console",
                    "analiza memoria cristal fallback nucleo" if index < 2 else "hola continuidad conversacional",
                    "ok",
                    "qwen2.5:3b-instruct",
                    "qwen2.5:3b-instruct",
                    f"2026-06-0{index + 1}",
                ),
            )
            conn.execute(
                "INSERT INTO signal_states (run_id, intent, tone, urgency, risk, pv7, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, "analyze" if index < 2 else "conversation", "constructive", "medium", "low", "{}", "[]"),
            )
            conn.execute(
                """INSERT INTO crystal_states
                (run_id, q_crystal, stability, q_delta, stability_delta, temporal_status)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, 0.5 + index * 0.1, 0.6 + index * 0.05, 0.04 * index, 0.02 * index, "improving" if index == 2 else "stable"),
            )
            conn.execute(
                """INSERT INTO verification_reports
                (run_id, status, coherence_score, memory_score, safety_score, usefulness_score, traceability_score, warnings, recommendations)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, "ok", 0.8, 0.7, 0.9, 0.8, 0.85, '["fallback observado"]' if index == 1 else "[]", "[]"),
            )
            conn.execute(
                """INSERT INTO model_events
                (run_id, role, provider, model_name, ok, error, quality_score)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (run_id, "hypothalamus", "ollama", "qwen2.5:3b-instruct", 1, None, 0.8),
            )
            conn.execute(
                """INSERT INTO model_events
                (run_id, role, provider, model_name, ok, error, quality_score)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (run_id, "central", "template" if index == 1 else "ollama", "template-fallback" if index == 1 else "qwen2.5:3b-instruct", 0 if index == 1 else 1, "boom" if index == 1 else None, 0.6),
            )
            conn.execute(
                "INSERT INTO episodic_memory (run_id, title, content, summary, tags) VALUES (?, ?, ?, ?, ?)",
                (run_id, "Run", "Usuario privado\nRespuesta", "Resumen", "triade,mvp,run"),
            )
    return db_path


def test_conversation_analyzer_produces_verifiable_json(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)

    payload = ConversationAnalyzer(db_path=db_path).analyze(limit=2, source="test")

    assert payload["status"] == "ok"
    assert payload["policy"]["mode"] == "read_only_analysis"
    assert payload["policy"]["identity_core_modified"] is False
    assert payload["summary"]["runs_analyzed"] == 2
    assert payload["model_usage"]["fallback_or_failed_events"] == 1
    assert payload["crystal_evolution"]["avg_q_crystal"] == 0.55
    assert "memoria" in payload["conversation_patterns"]["recurring_themes"]


def test_conversation_analyzer_exports_markdown_without_mutating_identity(tmp_path: Path) -> None:
    db_path = make_db(tmp_path)
    analyzer = ConversationAnalyzer(db_path=db_path)
    payload = analyzer.analyze(limit=50)
    before = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM identity_core").fetchone()[0]

    report_path = analyzer.export_markdown(payload, tmp_path / "report.md")

    after = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM identity_core").fetchone()[0]
    text = report_path.read_text(encoding="utf-8")
    assert before == after
    assert "Conversation Evolution Report" in text
    assert "Runs analizados: 3" in text
    assert "Que NO Debe Consolidarse Aun" in text

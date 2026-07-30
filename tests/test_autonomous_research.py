import sqlite3
from pathlib import Path

from triade.research.autonomous import (
    AutonomousResearchEngine,
    AutonomousResearchPolicy,
)


def _provider(query, *, max_sources):
    return {
        "sources": [
            {
                "url": "https://example.test/source",
                "title": "Material auxético · fuente verificable",
                "excerpt": "Un material auxético aumenta transversalmente al ser estirado; evidencia independiente con procedencia explícita. "
                * 4,
            }
        ]
    }


def test_identity_question_does_not_go_to_web(tmp_path):
    engine = AutonomousResearchEngine(tmp_path / "triade.db", search_provider=_provider)
    assert (
        engine.should_research(
            "¿Recuerdas fuera de esta sesión?",
            memory_confidence=0,
            authorized_matches=0,
        )[0]
        is False
    )


def test_gap_creates_candidate_not_stable_memory(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    db = tmp_path / "triade.db"
    engine = AutonomousResearchEngine(
        db,
        policy=AutonomousResearchPolicy(minimum_excerpt_chars=20),
        search_provider=_provider,
    )
    allowed, trigger = engine.should_research(
        "¿Qué es un material auxético?", memory_confidence=0, authorized_matches=0
    )
    assert allowed and trigger == "knowledge_gap"
    result = engine.research("¿Qué es un material auxético?", trigger=trigger)
    assert result["status"] == "candidate_created"
    assert result["stable_memory_written"] is False
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute("SELECT status FROM learning_queue").fetchone()[0]
            == "candidate"
        )


def test_sufficient_memory_and_sensitive_queries_are_blocked(tmp_path):
    engine = AutonomousResearchEngine(tmp_path / "triade.db", search_provider=_provider)
    assert (
        engine.should_research(
            "¿Qué es LoRA?", memory_confidence=0.9, authorized_matches=1
        )[1]
        == "memory_sufficient"
    )
    assert (
        engine.should_research(
            "¿Cuál es mi contraseña?", memory_confidence=0, authorized_matches=0
        )[1]
        == "sensitive_query"
    )

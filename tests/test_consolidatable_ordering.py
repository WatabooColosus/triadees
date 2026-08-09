"""La tanda de consolidación no puede gastarse en quien va a fallar seguro.

`list_consolidatable()` ordenaba sólo por `run_use_count DESC` y traía cinco.
Medido sobre la base real el 2026-08-09: los cinco primeros por uso (entre 17 y
44) eran siempre los mismos `internally_checked` **sin** evidencia Measurement
Core, así que `consolidate()` rechazaba la tanda entera —«No existe evidencia
Measurement Core»— en las 18 ejecuciones de `stable_consolidation_review` que
había en la base. El único candidato capaz de consolidar tenía 3 usos y no
entraba nunca.

Es la misma hambre por ordenación que ya se corrigió dos veces (por recencia en
la selección de evidencia, y otra vez en la tanda de consolidación); esta es la
tercera puerta.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.learning.pipeline import LearningPipeline

ESQUEMA = """
CREATE TABLE learning_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT UNIQUE, source_type TEXT, source_ref TEXT,
    title TEXT, content TEXT, normalized_summary TEXT, domain TEXT,
    risk_level TEXT DEFAULT 'low', confidence REAL DEFAULT 0.5,
    utility REAL DEFAULT 0.5, status TEXT DEFAULT 'candidate',
    verification_notes TEXT, created_at TEXT, updated_at TEXT,
    run_use_count INTEGER DEFAULT 0, run_outcome_scores TEXT,
    avg_outcome_score REAL DEFAULT 0.0);
CREATE TABLE learning_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT, decision TEXT);
"""


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """Reproduce la trampa: muchos usos sin evidencia, pocos usos con evidencia."""
    ruta = tmp_path / "triade.db"
    with sqlite3.connect(ruta) as conn:
        conn.executescript(ESQUEMA)
        # Cinco acaparadores: muchísimo uso, ninguna evidencia de mejora.
        for i, usos in enumerate((44, 25, 24, 23, 17)):
            conn.execute(
                """INSERT INTO learning_queue
                (candidate_id, source_ref, content, domain, status,
                 run_use_count, avg_outcome_score)
                VALUES (?, 'run:x', 'texto', 'general', 'internally_checked', ?, 0.93)""",
                (f"learn-acaparador-{i}", usos),
            )
        # El único que sí puede consolidar: pocos usos, evidencia de mejora.
        conn.execute(
            """INSERT INTO learning_queue
            (candidate_id, source_ref, content, domain, status,
             run_use_count, avg_outcome_score)
            VALUES ('exp-con-evidencia', 'run:A', 'texto', 'reporting',
                    'evidence_verified', 3, 1.0)"""
        )
        conn.execute(
            "INSERT INTO learning_evidence (candidate_id, decision) VALUES ('exp-con-evidencia','improved')"
        )
        # Un distractor con evidencia que NO demuestra mejora: no debe adelantar.
        conn.execute(
            """INSERT INTO learning_queue
            (candidate_id, source_ref, content, domain, status,
             run_use_count, avg_outcome_score)
            VALUES ('learn-neutral', 'run:y', 'texto', 'general',
                    'internally_checked', 20, 0.9)"""
        )
        conn.execute(
            "INSERT INTO learning_evidence (candidate_id, decision) VALUES ('learn-neutral','neutral')"
        )
    return ruta


def test_quien_trae_evidencia_de_mejora_entra_primero(db: Path) -> None:
    """Sin esto, los cinco huecos se los llevan los acaparadores y la tanda se rechaza entera."""
    elegibles = LearningPipeline(db_path=db).list_consolidatable(limit=5)
    assert elegibles, "debía haber candidatos elegibles"
    assert elegibles[0]["candidate_id"] == "exp-con-evidencia", (
        "el candidato con evidencia 'improved' debe encabezar la tanda aunque "
        "tenga muchos menos usos"
    )


def test_una_evidencia_que_no_mejora_no_adelanta(db: Path) -> None:
    """El criterio es `decision='improved'`, no «tener una fila de evidencia»."""
    ids = [
        c["candidate_id"]
        for c in LearningPipeline(db_path=db).list_consolidatable(limit=7)
    ]
    assert ids[0] == "exp-con-evidencia"
    # `learn-neutral` tiene 20 usos: compite por uso, no por su evidencia neutra.
    assert ids.index("learn-neutral") > 0


def test_los_umbrales_no_se_relajan(db: Path) -> None:
    """Ordenar distinto no es admitir a quien no califica."""
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO learning_queue
            (candidate_id, source_ref, content, domain, status,
             run_use_count, avg_outcome_score)
            VALUES ('exp-sin-usos', 'run:B', 'texto', 'reporting',
                    'evidence_verified', 1, 1.0)"""
        )
        conn.execute(
            "INSERT INTO learning_evidence (candidate_id, decision) VALUES ('exp-sin-usos','improved')"
        )
    ids = [
        c["candidate_id"]
        for c in LearningPipeline(db_path=db).list_consolidatable(limit=10)
    ]
    assert "exp-sin-usos" not in ids, (
        "con 1 uso no llega al mínimo de 3, tenga la evidencia que tenga"
    )

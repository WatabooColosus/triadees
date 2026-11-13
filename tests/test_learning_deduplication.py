"""Agrupar duplicados sin borrar nada, y poder deshacerlo.

En la base real hay 628 filas y 200 contenidos únicos; uno se repite 145 veces.
Sin agrupar, ese contenido tendría 145 votos en el retrieval frente a uno.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.learning.deduplication import LearningDeduplicator

PLANTILLA = (
    "Para la misión 'Misión fundacional · Impulso Pereza', mantener como "
    "hipótesis operacional que detectar inercia debe evaluarse con evidencia."
)


def _seed(db: Path, filas: list[dict]) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS learning_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id TEXT UNIQUE, source_type TEXT, source_ref TEXT,
            title TEXT, content TEXT, normalized_summary TEXT, domain TEXT,
            risk_level TEXT, confidence REAL, utility REAL, status TEXT,
            verification_notes TEXT, created_at TEXT, updated_at TEXT,
            run_use_count INTEGER DEFAULT 0, run_outcome_scores TEXT,
            avg_outcome_score REAL DEFAULT 0)"""
    )
    for f in filas:
        conn.execute(
            "INSERT INTO learning_queue (candidate_id, content, source_ref, "
            "risk_level, status, run_use_count, avg_outcome_score, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                f["candidate_id"],
                f["content"],
                f.get("source_ref", "run:origen"),
                f.get("risk_level", "low"),
                f.get("status", "internally_checked"),
                f.get("run_use_count", 0),
                f.get("avg_outcome_score", 0.0),
                f.get("created_at", "2026-07-01"),
            ),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "triade.db"


def _count_rows(db: Path) -> int:
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT count(*) FROM learning_queue").fetchone()[0]
    conn.close()
    return int(n)


def test_los_duplicados_exactos_se_agrupan(db: Path) -> None:
    _seed(
        db,
        [
            {"candidate_id": f"c{i}", "content": "El runbook es RBK-7731."}
            for i in range(3)
        ],
    )
    rep = LearningDeduplicator(db).analyze()
    assert len(rep.groups) == 1
    assert rep.duplicates == 2


def test_los_duplicados_normalizados_se_agrupan(db: Path) -> None:
    _seed(
        db,
        [
            {"candidate_id": "c1", "content": "El runbook es RBK-7731."},
            {"candidate_id": "c2", "content": "  el   RUNBOOK es rbk-7731  "},
        ],
    )
    rep = LearningDeduplicator(db).analyze()
    assert len(rep.groups) == 1


def test_las_plantillas_repetidas_se_agrupan(db: Path) -> None:
    _seed(db, [{"candidate_id": f"c{i}", "content": PLANTILLA} for i in range(5)])
    rep = LearningDeduplicator(db).analyze()
    assert len(rep.groups) == 1
    assert rep.duplicates == 4


def test_una_contradiccion_no_se_agrupa(db: Path) -> None:
    _seed(
        db,
        [
            {"candidate_id": "c1", "content": "El gate debe ejecutarse siempre."},
            {"candidate_id": "c2", "content": "El gate no debe ejecutarse siempre."},
        ],
    )
    rep = LearningDeduplicator(db).analyze()
    assert rep.groups == []
    assert rep.contradictions


def test_parecidos_pero_distintos_no_se_agrupan(db: Path) -> None:
    _seed(
        db,
        [
            {
                "candidate_id": "c1",
                "content": "El runbook de recuperación es RBK-7731.",
            },
            {"candidate_id": "c2", "content": "El runbook de despliegue es RBK-9902."},
        ],
    )
    assert LearningDeduplicator(db).analyze().groups == []


def test_el_canonico_conserva_la_mejor_procedencia(db: Path) -> None:
    _seed(
        db,
        [
            {"candidate_id": "sin-origen", "content": "mismo texto", "source_ref": ""},
            {
                "candidate_id": "con-origen",
                "content": "mismo texto",
                "run_use_count": 5,
            },
        ],
    )
    rep = LearningDeduplicator(db).analyze()
    assert rep.groups[0].canonical_candidate_id == "con-origen"


def test_no_se_borra_ninguna_fila(db: Path) -> None:
    _seed(db, [{"candidate_id": f"c{i}", "content": "mismo texto"} for i in range(4)])
    d = LearningDeduplicator(db)
    d.apply(d.analyze())
    assert _count_rows(db) == 4


def test_aplicar_es_idempotente(db: Path) -> None:
    _seed(db, [{"candidate_id": f"c{i}", "content": "mismo texto"} for i in range(4)])
    d = LearningDeduplicator(db)
    d.apply(d.analyze())
    suprimidos = d.suppressed_ids()
    d.apply(d.analyze())
    assert d.suppressed_ids() == suprimidos
    assert _count_rows(db) == 4


def test_el_grupo_puede_revertirse(db: Path) -> None:
    _seed(db, [{"candidate_id": f"c{i}", "content": "mismo texto"} for i in range(3)])
    d = LearningDeduplicator(db)
    rep = d.analyze()
    d.apply(rep)
    assert d.suppressed_ids()

    d.revert(rep.groups[0].group_id)
    assert d.suppressed_ids() == set()
    assert _count_rows(db) == 3


def test_el_canonico_se_resuelve_desde_cualquier_miembro(db: Path) -> None:
    _seed(
        db,
        [
            {"candidate_id": "bueno", "content": "mismo texto", "run_use_count": 9},
            {"candidate_id": "otro", "content": "mismo texto"},
        ],
    )
    d = LearningDeduplicator(db)
    d.apply(d.analyze())
    assert d.canonical_for("otro") == "bueno"
    assert d.canonical_for("bueno") == "bueno"
    assert d.canonical_for("inexistente") == "inexistente"


def test_el_conteo_de_unicos_coincide_con_la_auditoria(db: Path) -> None:
    _seed(
        db,
        [
            {"candidate_id": "a1", "content": "texto uno"},
            {"candidate_id": "a2", "content": "texto uno"},
            {"candidate_id": "b1", "content": "texto dos"},
        ],
    )
    rep = LearningDeduplicator(db).analyze()
    assert rep.total_rows == 3
    assert rep.unique_contents == 2
    assert rep.to_dict()["rows_deleted"] == 0

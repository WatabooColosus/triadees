"""Lo que se le enseña al usuario tiene que ser verdad.

El usuario decía «no veo saberes» con 633 candidatos en la base. Tenía razón:
un candidato no es un saber, y el panel llamaba «verificados» a los que estaban
en `internally_checked`, que es exactamente el estado sin evidencia.

Estos casos fijan que ningún candidato pueda disfrazarse de saber, y que un
cero se muestre como cero.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from triade.knowledge.visibility import (
    VISIBILITY_VERSION,
    KnowledgeVisibilityService,
)


def _seed(
    db: Path, candidatos: list[dict], evidencias: list[dict] | None = None
) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS learning_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT UNIQUE,
            source_type TEXT, source_ref TEXT, title TEXT, content TEXT,
            normalized_summary TEXT, domain TEXT, risk_level TEXT, confidence REAL,
            utility REAL, status TEXT, verification_notes TEXT, created_at TEXT,
            updated_at TEXT, run_use_count INTEGER DEFAULT 0,
            run_outcome_scores TEXT, avg_outcome_score REAL DEFAULT 0)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS learning_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT UNIQUE,
            hypothesis TEXT, capability TEXT, subject_id TEXT,
            baseline_evaluation_json TEXT, candidate_evaluation_json TEXT,
            comparison_json TEXT, decision TEXT, critical_regressions_json TEXT,
            artifact_ref TEXT, regression_required INTEGER, regression_report_id TEXT,
            created_at TEXT, updated_at TEXT)"""
    )
    for c in candidatos:
        conn.execute(
            "INSERT INTO learning_queue (candidate_id, title, content, domain, "
            "status, source_ref, risk_level, confidence, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                c["candidate_id"],
                c.get("title", "t"),
                c.get("content", "contenido"),
                c.get("domain", "general"),
                c.get("status", "internally_checked"),
                c.get("source_ref", "run:origen"),
                c.get("risk_level", "low"),
                c.get("confidence", 0.8),
                c.get("created_at", "2026-07-01T00:00:00+00:00"),
                c.get("updated_at", "2026-07-01T00:00:00+00:00"),
            ),
        )
    for e in evidencias or []:
        conn.execute(
            "INSERT INTO learning_evidence (candidate_id, decision, "
            "baseline_evaluation_json, candidate_evaluation_json, comparison_json, "
            "regression_report_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                e["candidate_id"],
                e.get("decision", "pending"),
                e.get("baseline"),
                e.get("candidate"),
                e.get("comparison"),
                e.get("regression_report_id"),
                "2026-07-01T00:00:00+00:00",
                "2026-07-01T00:00:00+00:00",
            ),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "triade.db"


# ── un candidato no es un saber ───────────────────────────────────────


def test_un_candidato_nunca_se_cuenta_como_saber(db: Path) -> None:
    _seed(db, [{"candidate_id": f"c{i}"} for i in range(5)])
    s = KnowledgeVisibilityService(db).summary()
    assert s.candidates == 5
    assert s.stable == 0
    assert s.evidence_verified == 0


def test_el_cero_se_muestra_como_cero_y_se_explica(db: Path) -> None:
    _seed(db, [{"candidate_id": "c1"}])
    s = KnowledgeVisibilityService(db).summary()
    assert s.stable + s.evidence_verified == 0
    assert "no es un saber" in s.status


def test_una_base_vacia_no_rompe_el_servicio(db: Path) -> None:
    _seed(db, [])
    s = KnowledgeVisibilityService(db).summary()
    assert s.candidates == 0
    assert s.status == "Sin candidatos ni saberes registrados."


def test_un_candidato_no_es_recuperable_ni_inyectable(db: Path) -> None:
    _seed(db, [{"candidate_id": "c1"}])
    item = KnowledgeVisibilityService(db).get_knowledge("c1")
    assert item is not None
    assert item.is_retrievable is False
    assert item.is_injectable is False
    assert item.is_visible_to_user is False


# ── la evidencia manda ────────────────────────────────────────────────


def test_una_evidencia_incompleta_no_asciende_a_nadie(db: Path) -> None:
    """Es el caso real: 1 fila con baseline, candidate y comparison en null."""
    _seed(
        db,
        [{"candidate_id": "c1"}],
        [{"candidate_id": "c1", "decision": "pending"}],
    )
    s = KnowledgeVisibilityService(db).summary()
    assert s.evidence_verified == 0
    item = KnowledgeVisibilityService(db).get_knowledge("c1")
    assert item.evidence_status.startswith("incomplete")


def test_una_evidencia_completa_y_con_gate_si_asciende(db: Path) -> None:
    _seed(
        db,
        [{"candidate_id": "c1"}],
        [
            {
                "candidate_id": "c1",
                "decision": "improved",
                "baseline": json.dumps({"score": 0.0}),
                "candidate": json.dumps({"score": 1.0}),
                "comparison": json.dumps({"absolute_delta": 0.42}),
                "regression_report_id": "rep-1",
            }
        ],
    )
    svc = KnowledgeVisibilityService(db)
    s = svc.summary()
    assert s.evidence_verified == 1
    assert s.candidates == 0

    item = svc.get_knowledge("c1")
    assert item.state == "evidence_verified"
    assert item.effect_delta == 0.42
    assert item.regression_status == "passed"
    assert item.is_visible_to_user is True
    assert item.is_injectable is True


def test_mejora_declarada_sin_gate_no_asciende(db: Path) -> None:
    """`improved` sin reporte de regresión no basta: el gate no se baja."""
    _seed(
        db,
        [{"candidate_id": "c1"}],
        [
            {
                "candidate_id": "c1",
                "decision": "improved",
                "baseline": json.dumps({}),
                "candidate": json.dumps({}),
                "comparison": json.dumps({"absolute_delta": 0.9}),
            }
        ],
    )
    assert KnowledgeVisibilityService(db).summary().evidence_verified == 0


def test_una_regresion_marca_el_saber_como_rechazado(db: Path) -> None:
    _seed(
        db,
        [{"candidate_id": "c1"}],
        [
            {
                "candidate_id": "c1",
                "decision": "regressed",
                "baseline": json.dumps({}),
                "candidate": json.dumps({}),
                "comparison": json.dumps({"absolute_delta": -0.5}),
            }
        ],
    )
    svc = KnowledgeVisibilityService(db)
    assert svc.summary().rejected == 1
    assert svc.get_knowledge("c1").is_injectable is False


# ── uso causal ────────────────────────────────────────────────────────


def test_el_uso_sale_de_la_inyeccion_no_del_contador_retrospectivo(db: Path) -> None:
    _seed(db, [{"candidate_id": "c1"}])
    conn = sqlite3.connect(db)
    conn.execute("UPDATE learning_queue SET run_use_count = 44")
    conn.execute(
        """CREATE TABLE learning_retrieval_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, routing_decision_id TEXT,
            query TEXT, requested_ids TEXT, retrieved_ids TEXT, authorized_ids TEXT,
            injected_ids TEXT, skipped TEXT, safety_verdicts TEXT,
            learning_context_hash TEXT, policy_version TEXT, created_at TEXT)"""
    )
    conn.commit()
    conn.close()

    item = KnowledgeVisibilityService(db).get_knowledge("c1")
    assert item.use_count_causal == 0, "44 usos retrospectivos no son uso causal"


def test_una_inyeccion_real_si_cuenta_como_uso(db: Path) -> None:
    _seed(db, [{"candidate_id": "c1"}])
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE learning_retrieval_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, routing_decision_id TEXT,
            query TEXT, requested_ids TEXT, retrieved_ids TEXT, authorized_ids TEXT,
            injected_ids TEXT, skipped TEXT, safety_verdicts TEXT,
            learning_context_hash TEXT, policy_version TEXT, created_at TEXT)"""
    )
    conn.execute(
        "INSERT INTO learning_retrieval_decisions (run_id, injected_ids, created_at)"
        " VALUES ('r1', ?, '2026-07-01T10:00:00+00:00')",
        (json.dumps(["c1"]),),
    )
    conn.commit()
    conn.close()

    item = KnowledgeVisibilityService(db).get_knowledge("c1")
    assert item.use_count_causal == 1
    assert item.last_used_at == "2026-07-01T10:00:00+00:00"


# ── duplicados y seguridad ────────────────────────────────────────────


def test_un_duplicado_no_se_cuenta_dos_veces(db: Path) -> None:
    _seed(db, [{"candidate_id": "c1"}, {"candidate_id": "c2"}])
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE learning_candidate_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT,
            canonical_candidate_id TEXT, member_candidate_id TEXT, match_type TEXT,
            similarity REAL, decision TEXT, created_at TEXT, policy_version TEXT)"""
    )
    conn.execute(
        "INSERT INTO learning_candidate_groups (group_id, canonical_candidate_id,"
        " member_candidate_id, match_type, similarity, decision, created_at,"
        " policy_version) VALUES ('g1','c1','c2','exact',1.0,'grouped','x','v1')"
    )
    conn.commit()
    conn.close()

    s = KnowledgeVisibilityService(db).summary()
    assert s.candidates == 1
    assert s.duplicates == 1


def test_faltar_las_tablas_nuevas_no_rompe_nada(db: Path) -> None:
    """En producción esas tablas aún no existen: eso es un cero, no un error."""
    _seed(db, [{"candidate_id": "c1"}])
    s = KnowledgeVisibilityService(db).summary()
    assert s.duplicates == 0
    assert s.used_today == 0


def test_la_version_de_visibilidad_viaja_en_el_resumen(db: Path) -> None:
    _seed(db, [])
    assert (
        KnowledgeVisibilityService(db).summary().visibility_version
        == VISIBILITY_VERSION
    )


def test_un_saber_inexistente_devuelve_none(db: Path) -> None:
    _seed(db, [])
    assert KnowledgeVisibilityService(db).get_knowledge("no-existe") is None

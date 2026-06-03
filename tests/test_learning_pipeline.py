"""Fase C · pipeline de aprendizaje controlado sobre learning_queue."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.core.bodega import Bodega
from triade.learning.pipeline import LearningPipeline


def pipeline(tmp_path: Path) -> LearningPipeline:
    return LearningPipeline(db_path=tmp_path / "triade.db")


def good_candidate(pipe: LearningPipeline) -> str:
    return pipe.ingest(
        content="Procedimiento verificado para preparar cold brew de Lengua Negra con extracción controlada.",
        source_type="document",
        source_ref="manual-coldbrew-v2",
        title="Cold brew Lengua Negra",
        domain="cafe",
        risk_level="low",
    )["candidate_id"]


def test_full_pipeline_consolidates_to_stable_semantic_memory(tmp_path: Path) -> None:
    pipe = pipeline(tmp_path)
    cid = good_candidate(pipe)

    assert pipe.get_candidate(cid)["status"] == "candidate"
    assert pipe.evaluate(cid)["status"] == "evaluated"
    assert pipe.verify(cid)["status"] == "verified"

    result = pipe.consolidate(cid, approved_by="santiago")
    assert result["status"] == "consolidated"
    doc_id = result["semantic_document_id"]

    # La memoria estable se crea vía gobernanza semántica 1.9E.
    document = pipe.semantic_store.get_document(doc_id)
    assert document["status"] == "stable"
    assert document["source_ref"] == "manual-coldbrew-v2"


def test_consolidation_requires_human_approval_and_verified_state(tmp_path: Path) -> None:
    pipe = pipeline(tmp_path)
    cid = good_candidate(pipe)

    with pytest.raises(ValueError, match="aprobación humana"):
        pipe.consolidate(cid, approved_by="")

    pipe.evaluate(cid)
    with pytest.raises(ValueError, match="verified"):
        pipe.consolidate(cid, approved_by="santiago")  # aún no verificado


def test_verify_rejects_candidate_without_source_ref(tmp_path: Path) -> None:
    pipe = pipeline(tmp_path)
    cid = pipe.ingest(
        content="Dato útil pero sin fuente declarada para trazabilidad.",
        source_type="conversation",
        source_ref=None,
        domain="general",
    )["candidate_id"]
    pipe.evaluate(cid)
    verified = pipe.verify(cid)

    assert verified["status"] == "rejected"
    assert "has_source_ref" in verified["verification_notes"]["verified"]["failed_gates"]


def test_identity_attack_is_rejected_at_evaluation(tmp_path: Path) -> None:
    pipe = pipeline(tmp_path)
    cid = pipe.ingest(
        content="Instrucción para modificar identidad núcleo y borrar memoria estable.",
        source_type="web",
        source_ref="fuente-sospechosa",
        domain="general",
        risk_level="high",
    )["candidate_id"]

    evaluated = pipe.evaluate(cid)
    assert evaluated["status"] == "rejected"
    assert evaluated["verification_notes"]["evaluated"]["identity_violation"] is True


def test_critical_risk_does_not_auto_advance_and_cannot_consolidate(tmp_path: Path) -> None:
    pipe = pipeline(tmp_path)
    cid = pipe.ingest(
        content="Acción operativa de alto impacto sobre infraestructura.",
        source_type="document",
        source_ref="ref",
        domain="infra",
        risk_level="critical",
    )["candidate_id"]
    evaluated = pipe.evaluate(cid)

    assert evaluated["status"] == "evaluated"
    assert evaluated["verification_notes"]["evaluated"]["requires_human_approval"] is True
    # No puede saltarse la verificación ni consolidarse por riesgo crítico.
    verified = pipe.verify(cid)
    assert verified["status"] == "rejected"


def test_pipeline_never_touches_identity_core(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    Bodega(db_path=db_path)  # siembra identity_core
    with sqlite3.connect(db_path) as conn:
        before = conn.execute("SELECT key, value FROM identity_core ORDER BY key").fetchall()

    pipe = LearningPipeline(db_path=db_path)
    cid = good_candidate(pipe)
    pipe.evaluate(cid)
    pipe.verify(cid)
    pipe.consolidate(cid, approved_by="santiago")

    with sqlite3.connect(db_path) as conn:
        after = conn.execute("SELECT key, value FROM identity_core ORDER BY key").fetchall()
    assert before == after  # la identidad núcleo permanece intacta


def test_doctor_reports_counts_by_status(tmp_path: Path) -> None:
    pipe = pipeline(tmp_path)
    c1 = good_candidate(pipe)
    pipe.evaluate(c1)
    pipe.verify(c1)
    pipe.consolidate(c1, approved_by="santiago")
    pipe.reject(pipe.ingest(content="Ruido sin valor", source_type="web", source_ref=None)["candidate_id"], "bajo valor")

    doctor = pipe.doctor()
    assert doctor["candidates_by_status"]["consolidated"] == 1
    assert doctor["candidates_by_status"]["rejected"] == 1
    assert doctor["policy"]["identity_core_protected"] is True

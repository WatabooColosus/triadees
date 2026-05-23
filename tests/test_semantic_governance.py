"""Tests de gobierno de memoria semántica 1.9E."""

from __future__ import annotations

import pytest

from triade.core.contracts import MemoryPacket
from triade.memory.semantic_governance import SemanticMemoryGovernance
from triade.memory.semantic_store import SemanticMemoryStore


def prepare(tmp_path, with_source: bool = True) -> tuple[SemanticMemoryStore, SemanticMemoryGovernance, str]:
    db_path = tmp_path / "semantic.db"
    store = SemanticMemoryStore(db_path=db_path)
    document = store.upsert_document(
        "El Cristal regula continuidad contextual.",
        domain="crystal",
        source_ref="evidencia-crystal" if with_source else None,
    )
    governance = SemanticMemoryGovernance(db_path=db_path)
    return store, governance, document.document_id


def vector_memory(document_id: str) -> MemoryPacket:
    return MemoryPacket(
        run_id="run-governance",
        semantic_matches=[
            {
                "document_id": document_id,
                "similarity": 0.88,
                "domain": "crystal",
                "source_ref": "evidencia-crystal",
                "retrieval_type": "vector_similarity",
            }
        ],
        semantic_recall={"enabled": True, "status": "ok", "matches_count": 1},
        confidence=0.80,
    )


def test_candidate_is_quarantined_and_cannot_raise_confidence(tmp_path) -> None:
    _, governance, document_id = prepare(tmp_path)

    memory = governance.govern_memory(vector_memory(document_id))

    assert memory.semantic_matches == []
    assert memory.confidence == 0.60
    policy = memory.semantic_recall["governance"]
    assert policy["allowed_vector_matches"] == 0
    assert policy["quarantined_vector_matches"] == 1
    assert policy["decisions"][0]["document_status"] == "candidate"
    assert policy["decisions"][0]["allowed_to_influence"] is False
    assert policy["confidence_before_governance"] == 0.80
    assert policy["confidence_after_governance"] == 0.60
    assert policy["removed_confidence_boost"] == 0.20


def test_experimental_requires_explicit_authorization(tmp_path) -> None:
    _, governance, document_id = prepare(tmp_path)
    governance.transition_document(document_id, "experimental", "Prueba inicial", approved_by="tester")

    blocked = governance.govern_memory(vector_memory(document_id), allow_experimental=False)
    allowed = governance.govern_memory(vector_memory(document_id), allow_experimental=True)

    assert blocked.semantic_matches == []
    assert blocked.confidence == 0.60
    assert allowed.semantic_matches[0]["document_status"] == "experimental"
    assert allowed.confidence == 0.80
    assert allowed.semantic_recall["governance"]["allowed_vector_matches"] == 1


def test_stable_is_allowed_preserves_source_and_confidence(tmp_path) -> None:
    _, governance, document_id = prepare(tmp_path)
    governance.transition_document(document_id, "experimental", "Prueba inicial", approved_by="tester")
    governance.transition_document(document_id, "stable", "Contenido comprobado", approved_by="tester")

    memory = governance.govern_memory(vector_memory(document_id))

    assert memory.semantic_matches[0]["document_status"] == "stable"
    assert memory.semantic_matches[0]["source_ref"] == "evidencia-crystal"
    assert memory.semantic_recall["authorized_matches_count"] == 1
    assert memory.confidence == 0.80
    assert memory.semantic_recall["governance"]["removed_confidence_boost"] == 0.0


def test_stable_requires_source_ref_and_valid_transitions(tmp_path) -> None:
    _, governance, document_id = prepare(tmp_path, with_source=False)

    with pytest.raises(ValueError, match="Transición no permitida"):
        governance.transition_document(document_id, "stable", "Salto inválido")
    governance.transition_document(document_id, "experimental", "Revisión inicial")
    with pytest.raises(ValueError, match="source_ref"):
        governance.transition_document(document_id, "stable", "Sin fuente")


def test_reingestion_does_not_downgrade_stable_document(tmp_path) -> None:
    store, governance, document_id = prepare(tmp_path)
    governance.transition_document(document_id, "experimental", "Revisión inicial")
    governance.transition_document(document_id, "stable", "Verificada")

    reingested = store.upsert_document(
        "El Cristal regula continuidad contextual.",
        domain="crystal",
        source_ref="evidencia-crystal",
        status="candidate",
    )

    assert reingested.document_id == document_id
    assert reingested.status == "stable"
    assert store.get_document(document_id)["status"] == "stable"


def test_governance_records_transition_events(tmp_path) -> None:
    _, governance, document_id = prepare(tmp_path)
    governance.transition_document(
        document_id,
        "experimental",
        "Evaluación controlada",
        approved_by="usuario",
        evidence={"phase": "1.9E"},
    )

    events = governance.list_events(document_id=document_id)
    doctor = governance.doctor()

    assert events[0]["previous_status"] == "candidate"
    assert events[0]["new_status"] == "experimental"
    assert events[0]["evidence"]["phase"] == "1.9E"
    assert doctor["documents_by_status"]["experimental"] == 1

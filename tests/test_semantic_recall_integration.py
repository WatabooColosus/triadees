"""Tests de integración de recall semántico al ciclo real de Tríade 1.9D."""

from __future__ import annotations

import json

from triade.core.bodega import Bodega
from triade.core.contracts import InputPacket
from triade.core.runner import TriadeRunner


class FakeSemanticSearchEngine:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "ok",
            "mode": "semantic-similarity-search-1.9C",
            "query": kwargs["query"],
            "model": kwargs.get("model") or "nomic-embed-text:latest",
            "query_dimensions": 768,
            "candidate_embeddings": 3,
            "matching_candidates": 1,
            "skipped_model": 0,
            "skipped_dimensions": 0,
            "results": [
                {
                    "document_id": "sem-crystal",
                    "similarity": 0.705043,
                    "embedding_model": "nomic-embed-text:latest",
                    "dimensions": 768,
                    "domain": "crystal",
                    "content": "El Cristal Morfológico regula estabilidad y continuidad contextual.",
                    "source_type": "manual-test",
                    "source_ref": "validacion-1.9C-crystal",
                    "metadata": {"phase": "1.9C"},
                }
            ],
        }


class FailingSemanticSearchEngine:
    def search(self, **kwargs):
        return {"status": "failed", "error": "embedding service unavailable", "results": []}


def test_bodega_keeps_vector_recall_disabled_by_default(tmp_path) -> None:
    engine = FakeSemanticSearchEngine()
    bodega = Bodega(db_path=tmp_path / "triade.db", semantic_search_engine=engine)
    packet = InputPacket(user_input="¿Qué regula la continuidad?", source="test", run_id="run-disabled")

    memory = bodega.recall(packet)

    assert memory.semantic_recall["enabled"] is False
    assert memory.semantic_recall["status"] == "disabled"
    assert engine.calls == []
    assert all(match.get("retrieval_type") != "vector_similarity" for match in memory.semantic_matches)


def test_bodega_injects_vector_matches_when_recall_is_enabled(tmp_path) -> None:
    engine = FakeSemanticSearchEngine()
    bodega = Bodega(db_path=tmp_path / "triade.db", semantic_search_engine=engine)
    packet = InputPacket(user_input="órgano que controla estabilidad", source="test", run_id="run-enabled")

    memory = bodega.recall(
        packet,
        semantic_recall_enabled=True,
        semantic_model="nomic-embed-text:latest",
        semantic_limit=2,
        semantic_min_similarity=0.6,
        semantic_domain="crystal",
    )

    assert memory.semantic_recall["enabled"] is True
    assert memory.semantic_recall["status"] == "ok"
    assert memory.semantic_recall["matches_count"] == 1
    assert memory.semantic_recall["strongest_similarity"] == 0.705043
    assert memory.semantic_matches[0]["retrieval_type"] == "vector_similarity"
    assert memory.semantic_matches[0]["document_id"] == "sem-crystal"
    assert engine.calls[0]["domain"] == "crystal"
    assert memory.confidence >= 0.8


def test_bodega_preserves_run_if_semantic_search_fails(tmp_path) -> None:
    bodega = Bodega(db_path=tmp_path / "triade.db", semantic_search_engine=FailingSemanticSearchEngine())
    packet = InputPacket(user_input="Consulta semántica", source="test", run_id="run-failed")

    memory = bodega.recall(packet, semantic_recall_enabled=True, semantic_model="nomic-embed-text:latest")

    assert memory.semantic_recall["status"] == "failed"
    assert memory.semantic_recall["error"] == "embedding service unavailable"
    assert memory.semantic_recall["matches_count"] == 0


def test_runner_persists_semantic_recall_in_auditable_artifacts(tmp_path) -> None:
    engine = FakeSemanticSearchEngine()
    runner = TriadeRunner(
        runs_dir=tmp_path / "runs",
        db_path=tmp_path / "triade.db",
        use_ollama=False,
        semantic_search_engine=engine,
    )

    result = runner.run(
        "órgano que controla estabilidad y evolución",
        source="test",
        semantic_recall_enabled=True,
        semantic_model="nomic-embed-text:latest",
        semantic_limit=3,
        semantic_min_similarity=0.6,
        semantic_domain="crystal",
    )
    run_path = tmp_path / "runs" / result["run_id"]
    memory = json.loads((run_path / "memory.json").read_text(encoding="utf-8"))
    memory_diff = json.loads((run_path / "memory_diff.json").read_text(encoding="utf-8"))
    integrity = json.loads((run_path / "integrity.json").read_text(encoding="utf-8"))

    assert result["semantic_recall"]["matches_count"] == 1
    assert memory["semantic_matches"][0]["document_id"] == "sem-crystal"
    assert memory["semantic_recall"]["status"] == "ok"
    assert memory_diff["semantic_recall"]["matches"][0]["retrieval_type"] == "vector_similarity"
    assert integrity["semantic_recall"]["model"] == "nomic-embed-text:latest"


def test_runner_without_semantic_recall_does_not_require_embedding_engine(tmp_path) -> None:
    runner = TriadeRunner(runs_dir=tmp_path / "runs", db_path=tmp_path / "triade.db", use_ollama=False)

    result = runner.run("Ciclo normal sin memoria vectorial", source="test")

    assert result["semantic_recall"]["enabled"] is False
    assert result["semantic_recall"]["status"] == "disabled"

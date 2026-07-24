"""Tests para el Knowledge Graph de TriadeOS."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.os.contracts import KGNode, KGEdge, KGContradiction
from triade.os.knowledge_graph import KnowledgeGraph


SCHEMA_SQL = Path(__file__).resolve().parents[1] / "triade" / "memory" / "schemas.sql"
MIGRATION_005 = Path(__file__).resolve().parents[1] / "triade" / "memory" / "migrations" / "005_triade_os.sql"


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test_triade.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if SCHEMA_SQL.exists():
        conn.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    if MIGRATION_005.exists():
        conn.executescript(MIGRATION_005.read_text(encoding="utf-8"))
    conn.close()
    return db_path


@pytest.fixture()
def kg(db: Path) -> KnowledgeGraph:
    return KnowledgeGraph(db_path=db)


class TestKGNodeCRUD:
    def test_add_fact_and_retrieve(self, kg: KnowledgeGraph) -> None:
        nid = kg.add_fact("El agua hierve a 100C", domain="ciencia", source_ref="test:1")
        assert nid > 0
        node = kg.get_node(nid)
        assert node is not None
        assert node.node_type == "fact"
        assert node.content == "El agua hierve a 100C"
        assert node.domain == "ciencia"
        assert node.source_ref == "test:1"

    def test_add_concept(self, kg: KnowledgeGraph) -> None:
        nid = kg.add_concept("Computacion cuantica", domain="tecnologia")
        node = kg.get_node(nid)
        assert node is not None
        assert node.node_type == "concept"

    def test_add_entity(self, kg: KnowledgeGraph) -> None:
        nid = kg.add_entity("Python", domain="lenguajes")
        node = kg.get_node(nid)
        assert node is not None
        assert node.node_type == "entity"

    def test_add_claim(self, kg: KnowledgeGraph) -> None:
        nid = kg.add_claim("Python es mejor que Java", domain="opinion")
        node = kg.get_node(nid)
        assert node is not None
        assert node.node_type == "claim"

    def test_add_hypothesis(self, kg: KnowledgeGraph) -> None:
        nid = kg.add_hypothesis("El cambio climatico es acelerado", domain="ciencia")
        node = kg.get_node(nid)
        assert node is not None
        assert node.node_type == "hypothesis"

    def test_get_nonexistent_node(self, kg: KnowledgeGraph) -> None:
        assert kg.get_node(9999) is None

    def test_update_node_evidence(self, kg: KnowledgeGraph) -> None:
        nid = kg.add_fact("Test update", domain="test")
        ok = kg.update_node_evidence(nid, "corroborated", confidence=0.75)
        assert ok is True
        node = kg.get_node(nid)
        assert node.evidence_level == "corroborated"
        assert node.confidence == 0.75


class TestKGSearch:
    def test_search_by_content(self, kg: KnowledgeGraph) -> None:
        kg.add_fact("Python es un lenguaje", domain="code")
        kg.add_fact("Java es un lenguaje", domain="code")
        kg.add_fact("Receta de pastel", domain="cocina")
        results = kg.search_nodes(query="lenguaje")
        assert len(results) == 2

    def test_search_by_domain(self, kg: KnowledgeGraph) -> None:
        kg.add_fact("A", domain="x")
        kg.add_fact("B", domain="y")
        results = kg.search_nodes(domain="x")
        assert len(results) == 1

    def test_search_by_evidence_level(self, kg: KnowledgeGraph) -> None:
        nid = kg.add_fact("Test", domain="test")
        kg.update_node_evidence(nid, "established", 0.9)
        kg.add_fact("Other", domain="test")
        results = kg.search_nodes(evidence_level="established")
        assert len(results) == 1
        assert results[0].id == nid

    def test_search_limit(self, kg: KnowledgeGraph) -> None:
        for i in range(10):
            kg.add_fact(f"Item {i}", domain="test")
        results = kg.search_nodes(limit=3)
        assert len(results) == 3

    def test_count_nodes(self, kg: KnowledgeGraph) -> None:
        kg.add_fact("A", domain="x")
        kg.add_fact("B", domain="x")
        assert kg.count_nodes() == 2
        assert kg.count_nodes(domain="x") == 2
        assert kg.count_nodes(domain="y") == 0


class TestKGEdges:
    def test_add_relation_and_retrieve(self, kg: KnowledgeGraph) -> None:
        a = kg.add_fact("A", domain="test")
        b = kg.add_fact("B", domain="test")
        eid = kg.add_relation(a, b, "supports", weight=0.8, evidence_refs=["ref1"])
        assert eid > 0
        edges = kg.get_edges(a, direction="out")
        assert len(edges) == 1
        assert edges[0].source_id == a
        assert edges[0].target_id == b
        assert edges[0].relation_type == "supports"

    def test_get_edges_incoming(self, kg: KnowledgeGraph) -> None:
        a = kg.add_fact("A", domain="test")
        b = kg.add_fact("B", domain="test")
        c = kg.add_fact("C", domain="test")
        kg.add_relation(a, b, "supports")
        kg.add_relation(c, b, "contradicts")
        edges_in = kg.get_edges(b, direction="in")
        assert len(edges_in) == 2

    def test_get_edges_both(self, kg: KnowledgeGraph) -> None:
        a = kg.add_fact("A", domain="test")
        b = kg.add_fact("B", domain="test")
        c = kg.add_fact("C", domain="test")
        kg.add_relation(a, b, "supports")
        kg.add_relation(b, c, "related_to")
        edges = kg.get_edges(b, direction="both")
        assert len(edges) == 2

    def test_find_relations(self, kg: KnowledgeGraph) -> None:
        a = kg.add_fact("A", domain="test")
        b = kg.add_fact("B", domain="test")
        kg.add_relation(a, b, "supports")
        kg.add_relation(a, b, "refines")
        supports = kg.find_relations(source_id=a, relation_type="supports")
        assert len(supports) == 1
        all_edges = kg.find_relations(source_id=a)
        assert len(all_edges) == 2


class TestKGTraversal:
    def test_query_node_basic(self, kg: KnowledgeGraph) -> None:
        a = kg.add_fact("Central", domain="core")
        b = kg.add_fact("Hypothalamus", domain="core")
        c = kg.add_fact("Bodega", domain="core")
        kg.add_relation(a, b, "depends_on")
        kg.add_relation(b, c, "depends_on")
        result = kg.query_node(a, depth=2)
        assert result["node"] is not None
        assert len(result["edges"]) >= 2
        assert len(result["neighbors"]) >= 1

    def test_query_nonexistent_node(self, kg: KnowledgeGraph) -> None:
        result = kg.query_node(9999)
        assert result["node"] is None
        assert result["edges"] == []
        assert result["neighbors"] == []


class TestKGContradictions:
    def test_detect_contradictions(self, kg: KnowledgeGraph) -> None:
        a = kg.add_fact("La tierra es plana", domain="test")
        b = kg.add_fact("La tierra es esferica", domain="test")
        kg.add_relation(a, b, "contradicts")
        contradictions = kg.detect_contradictions()
        assert len(contradictions) >= 1
        assert contradictions[0].node_a_id == min(a, b)
        assert contradictions[0].node_b_id == max(a, b)

    def test_detect_no_duplicate_contradictions(self, kg: KnowledgeGraph) -> None:
        a = kg.add_fact("X", domain="test")
        b = kg.add_fact("Y", domain="test")
        kg.add_relation(a, b, "contradicts")
        kg.detect_contradictions()
        kg.detect_contradictions()
        contradictions = kg.list_contradictions()
        assert len(contradictions) == 1

    def test_resolve_contradiction(self, kg: KnowledgeGraph) -> None:
        a = kg.add_fact("A", domain="test")
        b = kg.add_fact("B", domain="test")
        kg.add_relation(a, b, "contradicts")
        contradictions = kg.detect_contradictions()
        cid = contradictions[0].id
        ok = kg.resolve_contradiction(cid, "B es correcto")
        assert ok is True
        c = [x for x in kg.list_contradictions() if x.id == cid][0]
        assert c.resolution_status == "resolved"
        assert c.resolution == "B es correcto"

    def test_accept_contradiction(self, kg: KnowledgeGraph) -> None:
        a = kg.add_fact("A", domain="test")
        b = kg.add_fact("B", domain="test")
        kg.add_relation(a, b, "contradicts")
        contradictions = kg.detect_contradictions()
        ok = kg.accept_contradiction(contradictions[0].id)
        assert ok is True

    def test_list_by_status(self, kg: KnowledgeGraph) -> None:
        a = kg.add_fact("A", domain="test")
        b = kg.add_fact("B", domain="test")
        kg.add_relation(a, b, "contradicts")
        kg.detect_contradictions()
        unresolved = kg.list_contradictions(status="unresolved")
        assert len(unresolved) >= 1
        resolved = kg.list_contradictions(status="resolved")
        assert len(resolved) == 0


class TestConfidencePropagation:
    def test_propagate_support(self, kg: KnowledgeGraph) -> None:
        a = kg.add_fact("Base fact", domain="test")
        b = kg.add_fact("Supporting fact", domain="test")
        kg.add_relation(b, a, "supports", weight=1.0)
        updated = kg.propagate_confidence()
        assert updated >= 1
        node = kg.get_node(a)
        assert node.confidence > 0.0

    def test_propagate_contradiction(self, kg: KnowledgeGraph) -> None:
        a = kg.add_fact("Claim A", domain="test")
        b = kg.add_fact("Claim B", domain="test")
        kg.update_node_evidence(a, "candidate", confidence=0.8)
        kg.add_relation(b, a, "contradicts", weight=1.0)
        updated = kg.propagate_confidence()
        assert updated >= 1

    def test_no_update_when_stable(self, kg: KnowledgeGraph) -> None:
        a = kg.add_fact("Stable", domain="test")
        updated = kg.propagate_confidence()
        assert updated == 0


class TestDomainSummary:
    def test_summary_all(self, kg: KnowledgeGraph) -> None:
        kg.add_fact("A", domain="x")
        kg.add_fact("B", domain="y")
        summary = kg.get_domain_summary()
        assert summary["node_count"] == 2
        assert "fact" in summary["by_type"]

    def test_summary_by_domain(self, kg: KnowledgeGraph) -> None:
        kg.add_fact("A", domain="x")
        kg.add_fact("B", domain="x")
        summary = kg.get_domain_summary(domain="x")
        assert summary["node_count"] == 2

    def test_summary_contradictions(self, kg: KnowledgeGraph) -> None:
        a = kg.add_fact("A", domain="x")
        b = kg.add_fact("B", domain="x")
        kg.add_relation(a, b, "contradicts")
        kg.detect_contradictions()
        summary = kg.get_domain_summary(domain="x")
        assert summary["contradiction_count"] >= 1


class TestDoctor:
    def test_doctor(self, kg: KnowledgeGraph) -> None:
        kg.add_fact("A", domain="test")
        report = kg.doctor()
        assert report["status"] == "ok"
        assert report["total_nodes"] == 1
        assert report["total_edges"] == 0
        assert report["unresolved_contradictions"] == 0

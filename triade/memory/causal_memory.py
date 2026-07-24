"""Causal Memory: relaciones de causa-efecto sobre kg_nodes/kg_edges.

Opera sobre el schema existente (migration 005) para agregar, consultar
y propagar conocimiento causal sin duplicar tablas.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now


@dataclass(slots=True)
class CausalNode:
    id: str = ""
    node_type: str = "fact"
    content: str = ""
    domain: str = ""
    evidence_level: str = "candidate"
    confidence: float = 0.5
    source_ref: str = ""
    neuron_id: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "node_type": self.node_type, "content": self.content,
            "domain": self.domain, "evidence_level": self.evidence_level,
            "confidence": round(self.confidence, 4), "source_ref": self.source_ref,
            "neuron_id": self.neuron_id, "created_at": self.created_at, "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class CausalEdge:
    id: str = ""
    source_id: str = ""
    target_id: str = ""
    relation_type: str = "related_to"
    weight: float = 0.5
    evidence_refs: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "source_id": self.source_id, "target_id": self.target_id,
            "relation_type": self.relation_type, "weight": round(self.weight, 4),
            "evidence_refs": list(self.evidence_refs), "created_at": self.created_at,
        }


class CausalMemory:
    """Gestor de memoria causal sobre kg_nodes/kg_edges existentes."""

    VALID_NODE_TYPES = {"fact", "concept", "entity", "claim", "hypothesis"}
    VALID_EVIDENCE_LEVELS = {"candidate", "contested", "corroborated", "established", "canonical"}
    VALID_RELATIONS = {"supports", "contradicts", "refines", "depends_on", "originates_from", "related_to"}

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def add_node(
        self,
        *,
        content: str,
        node_type: str = "fact",
        domain: str = "",
        confidence: float = 0.5,
        source_ref: str = "",
        neuron_id: int = 0,
    ) -> CausalNode:
        now = utc_now()
        node_type = node_type if node_type in self.VALID_NODE_TYPES else "fact"
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO kg_nodes (node_type, content, domain, evidence_level, confidence, source_ref, neuron_id, created_at, updated_at)
                VALUES (?, ?, ?, 'candidate', ?, ?, ?, ?, ?)""",
                (node_type, content, domain, max(0, min(1, confidence)), source_ref, neuron_id, now, now),
            )
            node_id = str(cur.lastrowid)
        return CausalNode(
            id=node_id, node_type=node_type, content=content, domain=domain,
            evidence_level="candidate", confidence=confidence, source_ref=source_ref,
            neuron_id=str(neuron_id), created_at=now, updated_at=now,
        )

    def add_edge(
        self,
        *,
        source_id: str,
        target_id: str,
        relation_type: str = "related_to",
        weight: float = 0.5,
        evidence_refs: list[str] | None = None,
    ) -> CausalEdge:
        now = utc_now()
        relation_type = relation_type if relation_type in self.VALID_RELATIONS else "related_to"
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO kg_edges (source_id, target_id, relation_type, weight, evidence_refs, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (int(source_id), int(target_id), relation_type, max(0, min(1, weight)),
                 json.dumps(evidence_refs or [], ensure_ascii=False), now),
            )
            edge_id = str(cur.lastrowid)
        return CausalEdge(
            id=edge_id, source_id=source_id, target_id=target_id,
            relation_type=relation_type, weight=weight,
            evidence_refs=evidence_refs or [], created_at=now,
        )

    def get_node(self, node_id: str) -> CausalNode | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM kg_nodes WHERE id = ?", (node_id,)).fetchone()
            if row is None:
                return None
            return CausalNode(
                id=str(row["id"]), node_type=str(row["node_type"]),
                content=str(row["content"]), domain=str(row["domain"]),
                evidence_level=str(row["evidence_level"]),
                confidence=float(row["confidence"] or 0),
                source_ref=str(row["source_ref"] or ""),
                neuron_id=str(row["neuron_id"] or ""),
                created_at=str(row["created_at"] or ""),
                updated_at=str(row["updated_at"] or ""),
            )

    def get_edges_from(self, node_id: str, relation_type: str | None = None) -> list[CausalEdge]:
        with self._connect() as conn:
            if relation_type:
                rows = conn.execute(
                    "SELECT * FROM kg_edges WHERE source_id = ? AND relation_type = ?",
                    (node_id, relation_type),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM kg_edges WHERE source_id = ?", (node_id,)).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def get_edges_to(self, node_id: str, relation_type: str | None = None) -> list[CausalEdge]:
        with self._connect() as conn:
            if relation_type:
                rows = conn.execute(
                    "SELECT * FROM kg_edges WHERE target_id = ? AND relation_type = ?",
                    (node_id, relation_type),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM kg_edges WHERE target_id = ?", (node_id,)).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def propagate_confidence(self, node_id: str) -> float:
        node = self.get_node(node_id)
        if not node:
            return 0.0
        supports = self.get_edges_to(node_id, "supports")
        contradicts = self.get_edges_to(node_id, "contradicts")
        support_boost = sum(e.weight * 0.1 for e in supports)
        contradiction_penalty = sum(e.weight * 0.15 for e in contradicts)
        new_conf = max(0, min(1, node.confidence + support_boost - contradiction_penalty))
        if abs(new_conf - node.confidence) > 0.01:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE kg_nodes SET confidence = ?, updated_at = ? WHERE id = ?",
                    (round(new_conf, 4), utc_now(), node_id),
                )
        return new_conf

    def query_by_domain(self, domain: str, limit: int = 50) -> list[CausalNode]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM kg_nodes WHERE domain = ? ORDER BY confidence DESC LIMIT ?",
                (domain, limit),
            ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def query_by_type(self, node_type: str, limit: int = 50) -> list[CausalNode]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM kg_nodes WHERE node_type = ? ORDER BY confidence DESC LIMIT ?",
                (node_type, limit),
            ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def contradictions_for(self, node_id: str) -> list[dict[str, Any]]:
        edges = self.get_edges_to(node_id, "contradicts")
        results = []
        for edge in edges:
            source = self.get_node(edge.source_id)
            if source:
                results.append({
                    "contradictor": source.to_dict(),
                    "edge": edge.to_dict(),
                })
        return results

    def summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            node_count = conn.execute("SELECT COUNT(*) as c FROM kg_nodes").fetchone()["c"]
            edge_count = conn.execute("SELECT COUNT(*) as c FROM kg_edges").fetchone()["c"]
            types = conn.execute(
                "SELECT node_type, COUNT(*) as c FROM kg_nodes GROUP BY node_type"
            ).fetchall()
            relations = conn.execute(
                "SELECT relation_type, COUNT(*) as c FROM kg_edges GROUP BY relation_type"
            ).fetchall()
        return {
            "total_nodes": node_count,
            "total_edges": edge_count,
            "by_type": {r["node_type"]: r["c"] for r in types},
            "by_relation": {r["relation_type"]: r["c"] for r in relations},
        }

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> CausalNode:
        return CausalNode(
            id=str(row["id"]), node_type=str(row["node_type"]),
            content=str(row["content"]), domain=str(row["domain"]),
            evidence_level=str(row["evidence_level"]),
            confidence=float(row["confidence"] or 0),
            source_ref=str(row["source_ref"] or ""),
            neuron_id=str(row["neuron_id"] or ""),
            created_at=str(row["created_at"] or ""),
            updated_at=str(row["updated_at"] or ""),
        )

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> CausalEdge:
        refs = []
        try:
            refs = json.loads(str(row["evidence_refs"] or "[]"))
        except (json.JSONDecodeError, TypeError):
            pass
        return CausalEdge(
            id=str(row["id"]), source_id=str(row["source_id"]),
            target_id=str(row["target_id"]),
            relation_type=str(row["relation_type"]),
            weight=float(row["weight"] or 0),
            evidence_refs=refs,
            created_at=str(row["created_at"] or ""),
        )

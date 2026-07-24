"""Knowledge Graph vivo para TriadeOS.

Almacena nodos (facts, concepts, entities, claims, hypotheses),
relaciones (supports, contradicts, refines, depends_on, originates_from, related_to),
y contradictions con resolución. Todo en SQLite sobre triade.db.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now
from triade.os.contracts import (
    KGContradiction,
    KGEdge,
    KGNode,
)


class KnowledgeGraph:
    """Grafo de conocimiento vivo persistido en SQLite."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self._ensure_schema()

    # ── connection ────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _ensure_schema(self) -> None:
        migration = Path(__file__).resolve().parents[1] / "memory" / "migrations" / "005_triade_os.sql"
        if migration.exists():
            with self._connect() as conn:
                conn.executescript(migration.read_text(encoding="utf-8"))

    # ── CRUD: nodes ──────────────────────────────────────────

    def add_fact(
        self,
        content: str,
        domain: str | None = None,
        source_ref: str | None = None,
        neuron_id: int | None = None,
    ) -> int:
        return self._add_node("fact", content, domain, source_ref, neuron_id)

    def add_concept(self, content: str, domain: str | None = None) -> int:
        return self._add_node("concept", content, domain)

    def add_entity(self, content: str, domain: str | None = None) -> int:
        return self._add_node("entity", content, domain)

    def add_claim(
        self,
        content: str,
        domain: str | None = None,
        source_ref: str | None = None,
        neuron_id: int | None = None,
    ) -> int:
        return self._add_node("claim", content, domain, source_ref, neuron_id)

    def add_hypothesis(
        self,
        content: str,
        domain: str | None = None,
        source_ref: str | None = None,
        neuron_id: int | None = None,
    ) -> int:
        return self._add_node("hypothesis", content, domain, source_ref, neuron_id)

    def _add_node(
        self,
        node_type: str,
        content: str,
        domain: str | None = None,
        source_ref: str | None = None,
        neuron_id: int | None = None,
    ) -> int:
        now = utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO kg_nodes (node_type, content, domain, source_ref, neuron_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (node_type, content, domain, source_ref, neuron_id, now),
            )
            return int(cursor.lastrowid)

    def get_node(self, node_id: int) -> KGNode | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM kg_nodes WHERE id = ?", (node_id,)).fetchone()
        return self._row_to_node(row) if row else None

    def update_node_evidence(self, node_id: int, evidence_level: str, confidence: float | None = None) -> bool:
        now = utc_now()
        with self._connect() as conn:
            if confidence is not None:
                conn.execute(
                    "UPDATE kg_nodes SET evidence_level = ?, confidence = ?, updated_at = ? WHERE id = ?",
                    (evidence_level, confidence, now, node_id),
                )
            else:
                conn.execute(
                    "UPDATE kg_nodes SET evidence_level = ?, updated_at = ? WHERE id = ?",
                    (evidence_level, now, node_id),
                )
            return conn.total_changes > 0

    def search_nodes(
        self,
        query: str | None = None,
        domain: str | None = None,
        evidence_level: str | None = None,
        node_type: str | None = None,
        limit: int = 50,
    ) -> list[KGNode]:
        clauses: list[str] = []
        params: list[Any] = []
        if query:
            clauses.append("content LIKE ?")
            params.append(f"%{query}%")
        if domain:
            clauses.append("domain = ?")
            params.append(domain)
        if evidence_level:
            clauses.append("evidence_level = ?")
            params.append(evidence_level)
        if node_type:
            clauses.append("node_type = ?")
            params.append(node_type)
        where = " AND ".join(clauses) if clauses else "1=1"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM kg_nodes WHERE {where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def count_nodes(self, domain: str | None = None) -> int:
        with self._connect() as conn:
            if domain:
                row = conn.execute("SELECT COUNT(*) AS c FROM kg_nodes WHERE domain = ?", (domain,)).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS c FROM kg_nodes").fetchone()
        return int(row["c"]) if row else 0

    # ── CRUD: edges ──────────────────────────────────────────

    def add_relation(
        self,
        source_id: int,
        target_id: int,
        relation_type: str,
        weight: float = 1.0,
        evidence_refs: list[str] | None = None,
    ) -> int:
        now = utc_now()
        refs_json = json.dumps(evidence_refs or [], ensure_ascii=False)
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO kg_edges (source_id, target_id, relation_type, weight, evidence_refs, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (source_id, target_id, relation_type, weight, refs_json, now),
            )
            return int(cursor.lastrowid)

    def get_edges(self, node_id: int, direction: str = "both") -> list[KGEdge]:
        with self._connect() as conn:
            if direction == "out":
                rows = conn.execute("SELECT * FROM kg_edges WHERE source_id = ?", (node_id,)).fetchall()
            elif direction == "in":
                rows = conn.execute("SELECT * FROM kg_edges WHERE target_id = ?", (node_id,)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM kg_edges WHERE source_id = ? OR target_id = ?", (node_id, node_id)
                ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def find_relations(
        self,
        source_id: int | None = None,
        target_id: int | None = None,
        relation_type: str | None = None,
        limit: int = 100,
    ) -> list[KGEdge]:
        clauses: list[str] = []
        params: list[Any] = []
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if target_id is not None:
            clauses.append("target_id = ?")
            params.append(target_id)
        if relation_type:
            clauses.append("relation_type = ?")
            params.append(relation_type)
        where = " AND ".join(clauses) if clauses else "1=1"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM kg_edges WHERE {where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    # ── Graph traversal ───────────────────────────────────────

    def query_node(self, node_id: int, depth: int = 2) -> dict[str, Any]:
        node = self.get_node(node_id)
        if not node:
            return {"node": None, "edges": [], "neighbors": []}

        visited: set[int] = {node_id}
        all_edges: list[KGEdge] = []
        neighbor_ids: set[int] = set()

        frontier = [node_id]
        for _ in range(depth):
            next_frontier: list[int] = []
            for nid in frontier:
                edges = self.get_edges(nid)
                for e in edges:
                    all_edges.append(e)
                    other = e.target_id if e.source_id == nid else e.source_id
                    if other not in visited:
                        visited.add(other)
                        neighbor_ids.add(other)
                        next_frontier.append(other)
            frontier = next_frontier

        neighbors = []
        for nid in neighbor_ids:
            n = self.get_node(nid)
            if n:
                neighbors.append(n.to_dict())

        return {
            "node": node.to_dict(),
            "edges": [e.to_dict() for e in all_edges],
            "neighbors": neighbors,
        }

    # ── Contradictions ───────────────────────────────────────

    def detect_contradictions(self) -> list[KGContradiction]:
        with self._connect() as conn:
            existing = {
                (r["node_a_id"], r["node_b_id"])
                for r in conn.execute(
                    "SELECT node_a_id, node_b_id FROM kg_contradictions WHERE resolution_status != 'resolved'"
                ).fetchall()
            }

            contradict_edges = conn.execute(
                "SELECT source_id, target_id, evidence_refs FROM kg_edges WHERE relation_type = 'contradicts'"
            ).fetchall()

            new_contradictions: list[KGContradiction] = []
            now = utc_now()
            for edge in contradict_edges:
                pair = (min(edge["source_id"], edge["target_id"]), max(edge["source_id"], edge["target_id"]))
                if pair in existing:
                    continue
                a = conn.execute("SELECT content, domain FROM kg_nodes WHERE id = ?", (pair[0],)).fetchone()
                b = conn.execute("SELECT content, domain FROM kg_nodes WHERE id = ?", (pair[1],)).fetchone()
                if not a or not b:
                    continue
                desc = f"Contradicción: '{a['content'][:80]}' vs '{b['content'][:80]}'"
                cursor = conn.execute(
                    """INSERT INTO kg_contradictions (node_a_id, node_b_id, description, created_at)
                    VALUES (?, ?, ?, ?)""",
                    (pair[0], pair[1], desc, now),
                )
                new_contradictions.append(
                    KGContradiction(
                        id=int(cursor.lastrowid),
                        node_a_id=pair[0],
                        node_b_id=pair[1],
                        description=desc,
                        created_at=now,
                    )
                )
                existing.add(pair)
            return new_contradictions

    def list_contradictions(self, status: str | None = None, limit: int = 50) -> list[KGContradiction]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM kg_contradictions WHERE resolution_status = ? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM kg_contradictions ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._row_to_contradiction(r) for r in rows]

    def resolve_contradiction(self, contradiction_id: int, resolution: str) -> bool:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """UPDATE kg_contradictions
                SET resolution_status = 'resolved', resolution = ?, resolved_at = ?
                WHERE id = ? AND resolution_status IN ('unresolved', 'investigating')""",
                (resolution, now, contradiction_id),
            )
            return conn.total_changes > 0

    def accept_contradiction(self, contradiction_id: int) -> bool:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """UPDATE kg_contradictions
                SET resolution_status = 'accepted', resolved_at = ?
                WHERE id = ? AND resolution_status IN ('unresolved', 'investigating')""",
                (now, contradiction_id),
            )
            return conn.total_changes > 0

    # ── Confidence propagation ────────────────────────────────

    def propagate_confidence(self) -> int:
        updated = 0
        with self._connect() as conn:
            nodes = conn.execute("SELECT id, confidence FROM kg_nodes").fetchall()
            for node in nodes:
                nid = node["id"]
                base = float(node["confidence"])

                support_weight = float(
                    conn.execute(
                        "SELECT COALESCE(SUM(weight), 0) AS w FROM kg_edges WHERE target_id = ? AND relation_type = 'supports'",
                        (nid,),
                    ).fetchone()["w"]
                )
                contra_weight = float(
                    conn.execute(
                        "SELECT COALESCE(SUM(weight), 0) AS w FROM kg_edges WHERE target_id = ? AND relation_type = 'contradicts'",
                        (nid,),
                    ).fetchone()["w"]
                )

                new_conf = max(0.0, min(1.0, base + (support_weight * 0.1) - (contra_weight * 0.2)))

                if abs(new_conf - base) > 0.05:
                    new_level = self._confidence_to_level(new_conf)
                    conn.execute(
                        "UPDATE kg_nodes SET confidence = ?, evidence_level = ?, updated_at = ? WHERE id = ?",
                        (round(new_conf, 4), new_level, utc_now(), nid),
                    )
                    updated += 1

                if contra_weight > 0 and base >= 0.5:
                    conn.execute(
                        "UPDATE kg_nodes SET evidence_level = 'contested', updated_at = ? WHERE id = ? AND evidence_level NOT IN ('established','canonical')",
                        (utc_now(), nid),
                    )
        return updated

    # ── Domain summary ────────────────────────────────────────

    def get_domain_summary(self, domain: str | None = None) -> dict[str, Any]:
        with self._connect() as conn:
            if domain:
                node_count = conn.execute(
                    "SELECT COUNT(*) AS c FROM kg_nodes WHERE domain = ?", (domain,)
                ).fetchone()["c"]
                by_type = conn.execute(
                    "SELECT node_type, COUNT(*) AS c FROM kg_nodes WHERE domain = ? GROUP BY node_type",
                    (domain,),
                ).fetchall()
                by_evidence = conn.execute(
                    "SELECT evidence_level, COUNT(*) AS c FROM kg_nodes WHERE domain = ? GROUP BY evidence_level",
                    (domain,),
                ).fetchall()
                contra_count = conn.execute(
                    """SELECT COUNT(*) AS c FROM kg_contradictions kc
                    JOIN kg_nodes kn ON kc.node_a_id = kn.id
                    WHERE kn.domain = ? AND kc.resolution_status != 'resolved'""",
                    (domain,),
                ).fetchone()["c"]
            else:
                node_count = conn.execute("SELECT COUNT(*) AS c FROM kg_nodes").fetchone()["c"]
                by_type = conn.execute(
                    "SELECT node_type, COUNT(*) AS c FROM kg_nodes GROUP BY node_type"
                ).fetchall()
                by_evidence = conn.execute(
                    "SELECT evidence_level, COUNT(*) AS c FROM kg_nodes GROUP BY evidence_level"
                ).fetchall()
                contra_count = conn.execute(
                    "SELECT COUNT(*) AS c FROM kg_contradictions WHERE resolution_status != 'resolved'"
                ).fetchone()["c"]

            edge_count = conn.execute("SELECT COUNT(*) AS c FROM kg_edges").fetchone()["c"]

        return {
            "domain": domain,
            "node_count": node_count,
            "edge_count": edge_count,
            "contradiction_count": contra_count,
            "by_type": {r["node_type"]: r["c"] for r in by_type},
            "by_evidence": {r["evidence_level"]: r["c"] for r in by_evidence},
        }

    # ── Doctor ────────────────────────────────────────────────

    def doctor(self) -> dict[str, Any]:
        summary = self.get_domain_summary()
        unresolved = len(self.list_contradictions(status="unresolved"))
        return {
            "status": "ok",
            "total_nodes": summary["node_count"],
            "total_edges": summary["edge_count"],
            "unresolved_contradictions": unresolved,
            "by_type": summary["by_type"],
            "by_evidence": summary["by_evidence"],
            "db_path": str(self.db_path),
        }

    # ── Internal helpers ──────────────────────────────────────

    @staticmethod
    def _confidence_to_level(confidence: float) -> str:
        if confidence >= 0.9:
            return "canonical"
        if confidence >= 0.7:
            return "established"
        if confidence >= 0.3:
            return "corroborated"
        return "candidate"

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> KGNode:
        return KGNode(
            id=row["id"],
            node_type=row["node_type"],
            content=row["content"],
            domain=row["domain"],
            evidence_level=row["evidence_level"],
            confidence=float(row["confidence"]),
            source_ref=row["source_ref"],
            neuron_id=row["neuron_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> KGEdge:
        refs = []
        try:
            refs = json.loads(row["evidence_refs"])
        except (json.JSONDecodeError, TypeError):
            pass
        return KGEdge(
            id=row["id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            relation_type=row["relation_type"],
            weight=float(row["weight"]),
            evidence_refs=refs,
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_contradiction(row: sqlite3.Row) -> KGContradiction:
        return KGContradiction(
            id=row["id"],
            node_a_id=row["node_a_id"],
            node_b_id=row["node_b_id"],
            description=row["description"],
            resolution_status=row["resolution_status"],
            resolution=row["resolution"],
            resolved_at=row["resolved_at"],
            created_at=row["created_at"],
        )

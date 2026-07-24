"""Matriz completa de capacidades con grafo de dependencias y salud.

Proporciona vista global de todas las capacidades, sus dependencias,
estado actual, cobertura de evaluación y puntos de fallo.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CapabilityNode:
    capability_id: str
    name: str
    domain: str
    state: str
    critical: bool
    dependencies: tuple[str, ...]
    evaluation_suites: tuple[str, ...]
    rollback_policy: str | None
    has_baseline: bool = False
    last_evaluation_score: float | None = None
    quarantined: bool = False


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    source: str
    target: str
    edge_type: str = "requires"


@dataclass(frozen=True, slots=True)
class MatrixHealth:
    total_capabilities: int
    active: int
    experimental: int
    deprecated: int
    blocked: int
    critical_count: int
    critical_without_baseline: int
    without_rollback: int
    quarantined: int
    dependency_cycles: list[tuple[str, ...]]
    health_score: float


class CapabilityMatrix:
    """Construye y consulta la matriz de capacidades completa."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def build(self) -> dict[str, Any]:
        nodes = self._load_nodes()
        edges = self._build_edges(nodes)
        cycles = self._detect_cycles(nodes)
        health = self._compute_health(nodes, cycles)
        domain_map: dict[str, list[str]] = {}
        for node in nodes:
            domain_map.setdefault(node.domain, []).append(node.capability_id)
        return {
            "nodes": [self._node_to_dict(n) for n in nodes],
            "edges": [{"source": e.source, "target": e.target, "type": e.edge_type} for e in edges],
            "domains": domain_map,
            "cycles": [list(c) for c in cycles],
            "health": self._health_to_dict(health),
        }

    def _load_nodes(self) -> list[CapabilityNode]:
        from triade.regression.gate import RegressionGate

        gate = RegressionGate(db_path=self.db_path)
        nodes: list[CapabilityNode] = []
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT capability_id, payload_json FROM capability_registry"
                ).fetchall()
        except sqlite3.OperationalError:
            return nodes

        for row in rows:
            import json
            payload = json.loads(row["payload_json"])
            cap_id = payload.get("capability_id", row["capability_id"])
            target = gate.rollback_target(cap_id)
            has_baseline = target is not None
            nodes.append(CapabilityNode(
                capability_id=cap_id,
                name=payload.get("name", cap_id),
                domain=payload.get("domain", "unknown"),
                state=payload.get("state", "experimental"),
                critical=payload.get("critical", False),
                dependencies=tuple(payload.get("dependencies", [])),
                evaluation_suites=tuple(payload.get("evaluation_suites", [])),
                rollback_policy=payload.get("rollback_policy"),
                has_baseline=has_baseline,
            ))
        return nodes

    def _build_edges(self, nodes: list[CapabilityNode]) -> list[DependencyEdge]:
        node_ids = {n.capability_id for n in nodes}
        edges: list[DependencyEdge] = []
        for node in nodes:
            for dep in node.dependencies:
                if dep in node_ids:
                    edges.append(DependencyEdge(source=dep, target=node.capability_id))
        return edges

    def _detect_cycles(self, nodes: list[CapabilityNode]) -> list[tuple[str, ...]]:
        node_map = {n.capability_id: n for n in nodes}
        cycles: list[tuple[str, ...]] = []

        def dfs(node_id: str, path: list[str], visited: set[str]) -> None:
            if node_id not in node_map:
                return
            if node_id in path:
                cycle_start = path.index(node_id)
                cycles.append(tuple(path[cycle_start:] + [node_id]))
                return
            if node_id in visited:
                return
            visited.add(node_id)
            for dep in node_map[node_id].dependencies:
                dfs(dep, path + [node_id], visited)

        for node in nodes:
            dfs(node.capability_id, [], set())
        return cycles

    def _compute_health(self, nodes: list[CapabilityNode], cycles: list[tuple[str, ...]]) -> MatrixHealth:
        active = sum(1 for n in nodes if n.state == "active")
        experimental = sum(1 for n in nodes if n.state == "experimental")
        deprecated = sum(1 for n in nodes if n.state == "deprecated")
        blocked = sum(1 for n in nodes if n.state == "blocked")
        critical = [n for n in nodes if n.critical]
        critical_without = sum(1 for n in critical if not n.has_baseline)
        without_rollback = sum(1 for n in nodes if n.critical and not n.rollback_policy)
        quarantined = sum(1 for n in nodes if n.quarantined)
        total = len(nodes) or 1
        cycle_penalty = min(1.0, len(cycles) * 0.25)
        block_penalty = min(1.0, blocked * 0.2)
        critical_penalty = min(1.0, critical_without * 0.15)
        score = max(0.0, 1.0 - cycle_penalty - block_penalty - critical_penalty - (quarantined * 0.1))
        return MatrixHealth(
            total_capabilities=len(nodes),
            active=active,
            experimental=experimental,
            deprecated=deprecated,
            blocked=blocked,
            critical_count=len(critical),
            critical_without_baseline=critical_without,
            without_rollback=without_rollback,
            quarantined=quarantined,
            dependency_cycles=cycles,
            health_score=round(score, 3),
        )

    @staticmethod
    def _node_to_dict(node: CapabilityNode) -> dict[str, Any]:
        return {
            "capability_id": node.capability_id,
            "name": node.name,
            "domain": node.domain,
            "state": node.state,
            "critical": node.critical,
            "dependencies": list(node.dependencies),
            "evaluation_suites": list(node.evaluation_suites),
            "rollback_policy": node.rollback_policy,
            "has_baseline": node.has_baseline,
            "quarantined": node.quarantined,
        }

    @staticmethod
    def _health_to_dict(health: MatrixHealth) -> dict[str, Any]:
        return {
            "total": health.total_capabilities,
            "active": health.active,
            "experimental": health.experimental,
            "deprecated": health.deprecated,
            "blocked": health.blocked,
            "critical_count": health.critical_count,
            "critical_without_baseline": health.critical_without_baseline,
            "without_rollback": health.without_rollback,
            "quarantined": health.quarantined,
            "dependency_cycles": [list(c) for c in health.dependency_cycles],
            "health_score": health.health_score,
        }

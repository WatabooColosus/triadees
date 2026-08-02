from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

NodeKind = Literal["directory", "file", "module", "class", "function", "table", "run", "neuron", "task"]
NodeState = Literal["active", "disconnected", "legacy", "hidden", "protected", "failed", "unknown"]


@dataclass(frozen=True, slots=True)
class GraphNode:
    node_id: str
    kind: NodeKind
    label: str
    state: NodeState = "unknown"
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: str
    target: str
    relation: str
    evidence: str
    metadata: dict[str, object] = field(default_factory=dict)

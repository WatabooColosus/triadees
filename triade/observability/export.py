from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .contracts import GraphEdge, GraphNode


def export_graph(
    path: Path, nodes: list[GraphNode], edges: list[GraphEdge], *, graph_type: str
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "graph_type": graph_type,
        "nodes": [asdict(node) for node in nodes],
        "edges": [asdict(edge) for edge in edges],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str),
        encoding="utf-8",
    )

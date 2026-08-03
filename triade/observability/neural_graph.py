from __future__ import annotations

import sqlite3
from pathlib import Path

from .contracts import GraphEdge, GraphNode

RUNTIME_TABLES = {
    "runs": ("run", "run_id"),
    "autonomous_tasks": ("task", "id"),
    "neurons": ("neuron", "id"),
    "neuron_activity": ("neuron", "neuron_id"),
    "verification_reports": ("run", "run_id"),
    "neuron_education_sessions": ("neuron", "neuron_id"),
    "neuron_education_applications": ("neuron", "neuron_id"),
}


def build_neural_graph(
    db_path: Path, *, limit: int = 5000
) -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    if not db_path.exists():
        return [], []
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for table, (kind, identity) in RUNTIME_TABLES.items():
            if table not in tables:
                continue
            table_id = f"table:{table}"
            nodes[table_id] = GraphNode(table_id, "table", table, "active")
            columns = {
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            }
            if identity not in columns:
                continue
            for row in connection.execute(
                f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT ?", (limit,)
            ):
                value = row[identity]
                if value is None:
                    continue
                node_id = f"{kind}:{value}"
                nodes.setdefault(
                    node_id,
                    GraphNode(
                        node_id,
                        kind,
                        str(value),
                        _state_from_row(row),
                        _safe_metadata(row),
                    ),
                )
                edges.append(
                    GraphEdge(
                        table_id, node_id, "contains_runtime_record", f"sqlite:{table}"
                    )
                )
                _append_relations(table, row, node_id, nodes, edges)
    finally:
        connection.close()
    return list(nodes.values()), edges


def _state_from_row(row: sqlite3.Row) -> str:
    for field in ("status", "state", "outcome"):
        if field in row.keys() and row[field]:
            value = str(row[field]).lower()
            if value in {"failed", "dead_letter", "degraded"}:
                return "failed"
            if value in {"legacy", "retired"}:
                return "legacy"
            return "active"
    return "unknown"


def _safe_metadata(row: sqlite3.Row) -> dict[str, object]:
    allowed = {
        "status",
        "state",
        "outcome",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
        "task_type",
    }
    return {
        key: row[key] for key in row.keys() if key in allowed and row[key] is not None
    }


def _append_relations(
    table: str,
    row: sqlite3.Row,
    source: str,
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
) -> None:
    referenced: dict[str, str] = {}
    for field, kind, relation in (
        ("run_id", "run", "participates_in"),
        ("neuron_id", "neuron", "uses_neuron"),
        ("task_id", "task", "references_task"),
    ):
        if field not in row.keys() or row[field] is None:
            continue
        target = f"{kind}:{row[field]}"
        nodes.setdefault(target, GraphNode(target, kind, str(row[field]), "unknown"))
        referenced[kind] = target
        if target != source:
            edges.append(GraphEdge(source, target, relation, f"sqlite:{table}.{field}"))

    # Una fila de `neuron_activity` se identifica por su `neuron_id`, así que el
    # nodo del registro *es* la neurona: la arista `uses_neuron` salía de ella
    # hacia sí misma y se descartaba, y el vínculo run→neurona no se dibujaba
    # nunca. La relación vive entre las entidades que la fila referencia, no
    # sólo entre el registro y cada una de ellas.
    run = referenced.get("run")
    neuron = referenced.get("neuron")
    if run and neuron and run != neuron:
        edge = GraphEdge(run, neuron, "uses_neuron", f"sqlite:{table}.neuron_id")
        if edge not in edges:
            edges.append(edge)

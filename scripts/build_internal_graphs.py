"""Construye los grafos internos verificables de Tríade Ω.

Siete grafos, todos derivados del repositorio real y —cuando existe— de la base
viva abierta en `mode=ro`. La salida es determinista: mismo commit y misma base,
mismos bytes. Eso es lo que permite comparar dos commits y afirmar que algo
mejoró o empeoró.

    python scripts/build_internal_graphs.py --output artifacts/internal_graphs

Sin `--db`, o con una base ausente, el script sigue funcionando y marca la
evidencia de ejecución como `UNKNOWN` en lugar de inventarla.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from triade.observability.alias_debt import build_alias_debt
from triade.observability.code_graph import (
    build_call_graph,
    build_entrypoint_graph,
    build_import_graph,
    build_module_index,
    reachable_modules,
)
from triade.observability.contracts import GraphEdge, GraphNode
from triade.observability.export import export_graph
from triade.observability.file_graph import build_file_graph
from triade.observability.neural_graph import build_neural_graph
from triade.observability.render import legend, write_renderings
from triade.observability.runtime_graph import (
    build_organ_graph,
    build_table_graph,
    build_vital_chain_graph,
    build_worker_graph,
)


def _summarise(nodes: list[GraphNode], edges: list[GraphEdge]) -> dict[str, object]:
    states: dict[str, int] = {}
    for node in nodes:
        states[node.state] = states.get(node.state, 0) + 1
    return {"nodes": len(nodes), "edges": len(edges), "states": states}


def _commit_sha(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def build_all(
    root: Path, db_path: Path | None, output: Path, *, render: bool = True
) -> dict[str, object]:
    root = root.resolve()
    index = build_module_index(root)

    import_nodes, import_edges = build_import_graph(root, index)
    table_nodes, table_edges = build_table_graph(root, index, db_path)
    graphs: list[tuple[str, str, list[GraphNode], list[GraphEdge]]] = [
        ("file_graph", "physical_atlas", *build_file_graph(root)),
        ("import_graph", "modules_and_imports", import_nodes, import_edges),
        ("call_graph", "static_calls", *build_call_graph(root, index)),
        ("entrypoint_graph", "entrypoints", *build_entrypoint_graph(root, index)),
        (
            "worker_graph",
            "workers_and_task_types",
            *build_worker_graph(root, index, db_path, import_edges),
        ),
        (
            "table_graph",
            "sqlite_readers_writers",
            table_nodes,
            table_edges,
        ),
        (
            "organ_graph",
            "triade_organs",
            *build_organ_graph(root, index, db_path, import_edges),
        ),
        (
            "vital_chain_graph",
            "vital_continuity",
            *build_vital_chain_graph(root, index, db_path),
        ),
    ]
    if db_path is not None and db_path.exists():
        graphs.append(("neural_graph", "neural_runtime", *build_neural_graph(db_path)))

    summary: dict[str, object] = {}
    for stem, graph_type, nodes, edges in graphs:
        export_graph(output / f"{stem}.json", nodes, edges, graph_type=graph_type)
        if render:
            write_renderings(output, stem, nodes, edges, graph_type=graph_type)
        summary[stem] = _summarise(nodes, edges)

    # El análisis de alias es estructural y recorre todo el repositorio. Se
    # genera junto a los grafos, cuando el índice y la alcanzabilidad ya están
    # en memoria, para que la API y el único worker no repitan un escaneo de
    # decenas de segundos en cada consulta.
    table_profiles = {
        node.label: dict(node.metadata)
        for node in table_nodes
        if node.node_id.startswith("table:")
    }
    alias_report = build_alias_debt(
        root,
        index=index,
        db_path=db_path,
        table_profiles=table_profiles,
        reachable=reachable_modules(root, index),
    )
    (output / "alias_debt.json").write_text(
        json.dumps(alias_report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    generated_at = datetime.now(UTC).isoformat()
    commit_sha = _commit_sha(root)
    generation_id = f"{(commit_sha or 'unknown')[:12]}-{time.time_ns()}"
    index_payload = {
        "schema_version": 1,
        "generation_id": generation_id,
        "generated_at": generated_at,
        "commit_sha": commit_sha,
        "root": root.name,
        "database": str(db_path) if db_path and db_path.exists() else None,
        "database_size_bytes": db_path.stat().st_size
        if db_path and db_path.exists()
        else None,
        "output": str(output.resolve()),
        "legend": legend(),
        "graphs": summary,
    }
    (output / "index.json").write_text(
        json.dumps(index_payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Construye los grafos internos verificables de Tríade Ω"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--db", type=Path, default=Path("triade/memory/triade.db"))
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/internal_graphs")
    )
    parser.add_argument(
        "--no-render",
        action="store_true",
        help="Genera sólo JSON, sin DOT/Mermaid/Markdown",
    )
    args = parser.parse_args()

    db_path = args.db if args.db.is_absolute() else args.root / args.db
    summary = build_all(args.root, db_path, args.output, render=not args.no_render)
    for stem, data in summary.items():
        assert isinstance(data, dict)
        print(f"{stem}: {data['nodes']} nodes / {data['edges']} edges {data['states']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

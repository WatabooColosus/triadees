#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from triade.observability.export import export_graph
from triade.observability.file_graph import build_file_graph
from triade.observability.neural_graph import build_neural_graph


def main() -> int:
    parser = argparse.ArgumentParser(description="Construye los grafos internos verificables de Tríade Ω")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--db", type=Path, default=Path("triade/memory/triade.db"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/internal_graphs"))
    args = parser.parse_args()
    file_nodes, file_edges = build_file_graph(args.root)
    export_graph(args.output / "file_graph.json", file_nodes, file_edges, graph_type="physical_atlas")
    db_path = args.db if args.db.is_absolute() else args.root / args.db
    neural_nodes, neural_edges = build_neural_graph(db_path)
    export_graph(args.output / "neural_graph.json", neural_nodes, neural_edges, graph_type="neural_runtime")
    print(f"file_graph: {len(file_nodes)} nodes / {len(file_edges)} edges")
    print(f"neural_graph: {len(neural_nodes)} nodes / {len(neural_edges)} edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

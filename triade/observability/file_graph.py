from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path

from .contracts import GraphEdge, GraphNode, NodeKind, NodeState

SENSITIVE_NAMES = {".env", ".git", ".ssh", "secrets", "credentials"}
SKIP_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    # Dependencias descargadas y objetos de Git: 84 000 nodos que no son Tríade
    # y que ahogan el atlas del sistema propio.
    "node_modules",
    ".git",
}
#: Directorios que son **salida** del sistema, no su estructura. Se inventarían
#: —cuántas entradas y cuánto pesan— pero no se expanden: `runs/` aportaba
#: 74 665 nodos, ocho veces todo el código, y con eso el atlas dejaba de leerse.
DATA_DIRS = {"runs", "artifacts", "logs", ".triade_trash", "models", "data"}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _protected(path: Path) -> bool:
    lowered = {part.lower() for part in path.parts}
    return any(name in lowered for name in SENSITIVE_NAMES)


def _node_id(root: Path, path: Path) -> str:
    relative = path.relative_to(root).as_posix()
    if _protected(path):
        return f"crypt:{_digest(relative)}"
    return f"path:{relative or '.'}"


def build_file_graph(root: Path) -> tuple[list[GraphNode], list[GraphEdge]]:
    root = root.resolve()
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    seen: set[str] = set()

    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_PARTS)
        if (
            current_path != root
            and current_path.parent == root
            and current_path.name in DATA_DIRS
        ):
            dirs[:] = []
            files = []
        entries = [
            *(current_path / d for d in dirs),
            *(current_path / f for f in sorted(files)),
        ]
        for path in entries:
            node_id = _node_id(root, path)
            if node_id in seen:
                continue
            seen.add(node_id)
            protected = _protected(path)
            hidden = any(part.startswith(".") for part in path.relative_to(root).parts)
            state: NodeState = (
                "protected" if protected else "hidden" if hidden else "active"
            )
            kind: NodeKind = "directory" if path.is_dir() else "file"
            metadata: dict[str, object] = {"protected": protected, "hidden": hidden}
            if path.is_file() and not protected:
                metadata["size"] = path.stat().st_size
                metadata["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            if path.is_dir() and path.parent == root and path.name in DATA_DIRS:
                # No se expande, pero se cuenta: el volumen de salida es
                # evidencia de ejecución y no debe desaparecer del atlas.
                metadata["data_dir"] = True
                metadata["entries"] = sum(1 for _ in path.iterdir())
            nodes.append(
                GraphNode(
                    node_id,
                    kind,
                    path.name,
                    state,
                    metadata,
                )
            )

            parent = path.parent
            if parent == root or root in parent.parents:
                edges.append(
                    GraphEdge(_node_id(root, parent), node_id, "contains", "filesystem")
                )

            if path.suffix == ".py" and path.is_file() and not protected:
                _append_python_edges(root, path, nodes, edges)

    return nodes, edges


def _append_python_edges(
    root: Path, path: Path, nodes: list[GraphNode], edges: list[GraphEdge]
) -> None:
    source = _node_id(root, path)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return
    for item in ast.walk(tree):
        if isinstance(item, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in item.names]
            module = item.module if isinstance(item, ast.ImportFrom) else None
            for name in names:
                target = f"module:{module or name}"
                nodes.append(GraphNode(target, "module", module or name, "unknown"))
                edges.append(
                    GraphEdge(
                        source,
                        target,
                        "imports",
                        f"{path}:{getattr(item, 'lineno', 0)}",
                    )
                )
        elif isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            kind: NodeKind = "class" if isinstance(item, ast.ClassDef) else "function"
            target = (
                f"symbol:{path.relative_to(root).as_posix()}:{item.name}:{item.lineno}"
            )
            nodes.append(
                GraphNode(target, kind, item.name, "active", {"line": item.lineno})
            )
            edges.append(GraphEdge(source, target, "defines", f"{path}:{item.lineno}"))

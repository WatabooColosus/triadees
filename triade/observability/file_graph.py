from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path

from .contracts import GraphEdge, GraphNode

SENSITIVE_NAMES = {".env", ".git", ".ssh", "secrets", "credentials"}
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


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
        entries = [*(current_path / d for d in dirs), *(current_path / f for f in sorted(files))]
        for path in entries:
            node_id = _node_id(root, path)
            if node_id in seen:
                continue
            seen.add(node_id)
            protected = _protected(path)
            hidden = any(part.startswith(".") for part in path.relative_to(root).parts)
            state = "protected" if protected else "hidden" if hidden else "active"
            metadata: dict[str, object] = {"protected": protected, "hidden": hidden}
            if path.is_file() and not protected:
                metadata["size"] = path.stat().st_size
                metadata["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            nodes.append(GraphNode(node_id, "directory" if path.is_dir() else "file", path.name, state, metadata))

            parent = path.parent
            if parent == root or root in parent.parents:
                edges.append(GraphEdge(_node_id(root, parent), node_id, "contains", "filesystem"))

            if path.suffix == ".py" and path.is_file() and not protected:
                _append_python_edges(root, path, nodes, edges)

    return nodes, edges


def _append_python_edges(root: Path, path: Path, nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
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
                edges.append(GraphEdge(source, target, "imports", f"{path}:{getattr(item, 'lineno', 0)}"))
        elif isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "class" if isinstance(item, ast.ClassDef) else "function"
            target = f"symbol:{path.relative_to(root).as_posix()}:{item.name}:{item.lineno}"
            nodes.append(GraphNode(target, kind, item.name, "active", {"line": item.lineno}))
            edges.append(GraphEdge(source, target, "defines", f"{path}:{item.lineno}"))

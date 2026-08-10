"""Grafos derivados del código real: módulos, llamadas y entrypoints.

Complementa `file_graph`, que describe el sistema de archivos. Aquí sólo entra
lo que puede demostrarse leyendo el AST del repositorio: un import se resuelve a
un fichero que existe, una llamada se registra cuando el símbolo destino es
único, y un entrypoint se declara cuando alguien lo arranca de verdad.

Nada de esto consulta la documentación ni la base viva.
"""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .contracts import GraphEdge, GraphNode, NodeState

SKIP_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "site-packages",
    # Salidas del propio runtime. `runs/` contenía 20.139 directorios en la
    # máquina certificada y ningún módulo Python; recorrerlos no añade código a
    # la verdad estructural, sólo convierte cada pulso en trabajo inútil.
    "runs",
    "artifacts",
    ".triade_trash",
    "logs",
}
SENSITIVE_NAMES = {".env", ".ssh", "secrets", "credentials"}

#: Ficheros de arranque que no son Python pero deciden qué Python se ejecuta.
_LAUNCH_CONFIG_GLOBS = (
    "Procfile",
    "Dockerfile",
    "Dockerfile.*",
    "systemd/*.service",
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
)
_MODULE_LAUNCH = re.compile(r"python[0-9.]*\s+-m\s+([A-Za-z_][\w.]*)")
_UVICORN_LAUNCH = re.compile(r"(?:uvicorn|--factory)\s+([A-Za-z_][\w.]*):(\w+)")
_SCRIPT_LAUNCH = re.compile(r"python[0-9.]*\s+([\w./-]+\.py)")


def _is_sensitive(path: Path) -> bool:
    return any(part.lower() in SENSITIVE_NAMES for part in path.parts)


def iter_python_files(root: Path) -> Iterator[Path]:
    """Recorre el repositorio en orden estable, saltando ruido y secretos."""
    found: list[Path] = []
    for directory, directories, files in os.walk(root, topdown=True):
        # Podar aquí es esencial: filtrar después de `rglob` todavía obliga a
        # recorrer .git, node_modules y las cachés (más de 20.000 directorios
        # en la instalación productiva observada).
        directories[:] = sorted(
            name
            for name in directories
            if name not in SKIP_PARTS and name.lower() not in SENSITIVE_NAMES
        )
        base = Path(directory)
        found.extend(base / name for name in files if name.endswith(".py"))
    yield from sorted(found)


def module_name(root: Path, path: Path) -> str:
    """Nombre punteado del módulo tal y como lo vería un `import`."""
    relative = path.relative_to(root)
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][: -len(".py")]
    return ".".join(parts)


@dataclass(frozen=True, slots=True)
class ModuleIndex:
    """Índice de módulos internos: el único universo que podemos resolver."""

    by_module: dict[str, str]
    by_path: dict[str, str]

    def resolve(self, dotted: str) -> str | None:
        """Devuelve la ruta del módulo interno, o el paquete que lo contiene."""
        candidate = dotted
        while candidate:
            if candidate in self.by_module:
                return self.by_module[candidate]
            candidate = candidate.rpartition(".")[0]
        return None


def build_module_index(root: Path) -> ModuleIndex:
    by_module: dict[str, str] = {}
    by_path: dict[str, str] = {}
    for path in iter_python_files(root):
        relative = path.relative_to(root).as_posix()
        dotted = module_name(root, path)
        by_module[dotted] = relative
        by_path[relative] = dotted
    return ModuleIndex(by_module=by_module, by_path=by_path)


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
        return None


def _absolute_module(
    dotted: str | None, level: int, current: str, *, is_package: bool = False
) -> str | None:
    """Traduce un import relativo (`from . import x`) a su nombre absoluto.

    La distinción que importa: un módulo `a.b.c` vive *dentro* del paquete
    `a.b`, pero un `a/b/__init__.py` **es** el paquete `a.b`. Tratar los dos
    igual sube un nivel de más en los `__init__`, y entonces
    `from .bootstrap import x` dentro de `triade/capabilities/__init__.py`
    resolvía a `triade.bootstrap`, que no existe. El módulo real quedaba sin
    importador y el grafo lo daba por muerto.
    """
    if not level:
        return dotted
    base = current.split(".")
    package = base if is_package else (base[:-1] if len(base) > 1 else base)
    trimmed = package[: len(package) - (level - 1)] if level > 1 else package
    if not trimmed:
        return dotted
    return ".".join([*trimmed, dotted]) if dotted else ".".join(trimmed)


def build_import_graph(
    root: Path, index: ModuleIndex | None = None
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Grafo 1: módulos e imports, con el destino resuelto a fichero real.

    Los imports externos se conservan como nodos aparte para poder auditar
    dependencias, pero nunca se confunden con módulos del repositorio.
    """
    root = root.resolve()
    index = index or build_module_index(root)
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    imported: set[str] = set()

    for relative, dotted in sorted(index.by_path.items()):
        node_id = f"module:{relative}"
        nodes[node_id] = GraphNode(
            node_id,
            "module",
            dotted,
            "active",
            {"path": relative, "internal": True},
        )

    for relative, dotted in sorted(index.by_path.items()):
        tree = _parse(root / relative)
        if tree is None:
            nodes[f"module:{relative}"] = GraphNode(
                f"module:{relative}",
                "module",
                dotted,
                "unknown",
                {"path": relative, "internal": True, "unparsable": True},
            )
            continue
        source = f"module:{relative}"
        for item in ast.walk(tree):
            targets: list[str] = []
            if isinstance(item, ast.Import):
                targets = [alias.name for alias in item.names]
            elif isinstance(item, ast.ImportFrom):
                absolute = _absolute_module(
                    item.module,
                    item.level,
                    dotted,
                    is_package=relative.endswith("__init__.py"),
                )
                if absolute is None:
                    continue
                # `from pkg import mod` puede apuntar a un submódulo o a un símbolo.
                targets = [absolute, *(f"{absolute}.{a.name}" for a in item.names)]
            else:
                continue
            for target in targets:
                resolved = index.resolve(target)
                if resolved is not None:
                    if resolved == relative:
                        continue
                    target_id = f"module:{resolved}"
                    imported.add(target_id)
                    relation = "imports"
                else:
                    root_package = target.partition(".")[0]
                    target_id = f"external:{root_package}"
                    nodes.setdefault(
                        target_id,
                        GraphNode(
                            target_id,
                            "module",
                            root_package,
                            "unknown",
                            {"internal": False},
                        ),
                    )
                    relation = "imports_external"
                edge = GraphEdge(
                    source,
                    target_id,
                    relation,
                    f"{relative}:{getattr(item, 'lineno', 0)}",
                )
                if edge not in edges:
                    edges.append(edge)

    # Python ejecuta el `__init__.py` de un paquete al importar cualquier módulo
    # de dentro, aunque nadie lo nombre. Contarlo como huérfano marcaba como
    # código muerto el `__init__` de paquetes en uso —incluido el de este mismo
    # módulo—, que es una conclusión que el propio import desmiente.
    for node_id in list(imported):
        relative = node_id.partition(":")[2]
        parts = relative.split("/")[:-1]
        while parts:
            package_init = f"module:{'/'.join([*parts, '__init__.py'])}"
            if package_init in nodes:
                imported.add(package_init)
            parts.pop()

    for node_id, node in nodes.items():
        if not node.metadata.get("internal") or node_id in imported:
            continue
        nodes[node_id] = GraphNode(
            node.node_id,
            node.kind,
            node.label,
            "disconnected",
            {**node.metadata, "imported_by": 0},
        )

    return sorted(nodes.values(), key=lambda n: n.node_id), edges


@dataclass(frozen=True, slots=True)
class SymbolTable:
    """Símbolos definidos por fichero, y su índice global por nombre simple."""

    definitions: dict[str, tuple[str, int]]
    by_name: dict[str, list[str]]


def build_symbol_table(root: Path, index: ModuleIndex) -> SymbolTable:
    definitions: dict[str, tuple[str, int]] = {}
    by_name: dict[str, list[str]] = {}
    for relative in sorted(index.by_path):
        tree = _parse(root / relative)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            symbol_id = f"symbol:{relative}:{node.name}"
            if symbol_id in definitions:
                continue
            definitions[symbol_id] = (relative, node.lineno)
            by_name.setdefault(node.name, []).append(symbol_id)
    return SymbolTable(definitions=definitions, by_name=by_name)


def _called_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def build_call_graph(
    root: Path, index: ModuleIndex | None = None
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Grafo 2: llamadas entre funciones y clases demostrables estáticamente.

    Sólo se registra la arista cuando el nombre invocado corresponde a **una**
    definición en todo el repositorio. Si hay homónimos no se adivina: el
    símbolo se marca como ambiguo y la llamada no se dibuja.
    """
    root = root.resolve()
    index = index or build_module_index(root)
    symbols = build_symbol_table(root, index)

    nodes: dict[str, GraphNode] = {}
    for symbol_id, (relative, lineno) in symbols.definitions.items():
        name = symbol_id.rpartition(":")[2]
        nodes[symbol_id] = GraphNode(
            symbol_id,
            "class" if name[:1].isupper() else "function",
            name,
            "unknown",
            {
                "path": relative,
                "line": lineno,
                "ambiguous": len(symbols.by_name[name]) > 1,
            },
        )

    edges: list[GraphEdge] = []
    called: set[str] = set()
    for relative in sorted(index.by_path):
        tree = _parse(root / relative)
        if tree is None:
            continue
        # Cada llamada se atribuye a la función que la contiene, no al fichero.
        stack: list[str] = []
        for ast_node, enclosing in _walk_with_scope(tree, relative, stack):
            if not isinstance(ast_node, ast.Call):
                continue
            called_name = _called_name(ast_node)
            if called_name is None:
                continue
            candidates = symbols.by_name.get(called_name)
            if not candidates or len(candidates) != 1:
                continue
            target = candidates[0]
            if enclosing is None or enclosing == target:
                continue
            called.add(target)
            edge = GraphEdge(
                enclosing,
                target,
                "calls",
                f"{relative}:{getattr(ast_node, 'lineno', 0)}",
            )
            if edge not in edges:
                edges.append(edge)

    for symbol_id, graph_node in nodes.items():
        state: NodeState = "active" if symbol_id in called else "disconnected"
        nodes[symbol_id] = GraphNode(
            graph_node.node_id,
            graph_node.kind,
            graph_node.label,
            state,
            {**graph_node.metadata, "called": symbol_id in called},
        )

    return sorted(nodes.values(), key=lambda n: n.node_id), edges


def _walk_with_scope(
    tree: ast.Module, relative: str, stack: list[str]
) -> Iterator[tuple[ast.AST, str | None]]:
    """Recorre el AST anotando en qué símbolo definido está cada nodo."""

    def visit(node: ast.AST) -> Iterator[tuple[ast.AST, str | None]]:
        pushed = False
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            stack.append(f"symbol:{relative}:{node.name}")
            pushed = True
        yield node, stack[-1] if stack else None
        for child in ast.iter_child_nodes(node):
            yield from visit(child)
        if pushed:
            stack.pop()

    for child in ast.iter_child_nodes(tree):
        yield from visit(child)


def build_entrypoint_graph(
    root: Path, index: ModuleIndex | None = None
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Grafo 3: entrypoints reales y quién los arranca.

    Un guard `__main__` prueba que el fichero *puede* ejecutarse solo. Que
    alguien lo ejecute de verdad sólo lo prueban Procfile, Dockerfile, unidades
    systemd, workflows y `[project.scripts]`.
    """
    root = root.resolve()
    index = index or build_module_index(root)
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    for relative in sorted(index.by_path):
        tree = _parse(root / relative)
        if tree is None:
            continue
        for ast_node in ast.walk(tree):
            if not isinstance(ast_node, ast.If):
                continue
            if not _is_main_guard(ast_node.test):
                continue
            node_id = f"entrypoint:{relative}"
            administrative = _administrative_on_demand(tree, relative)
            nodes[node_id] = GraphNode(
                node_id,
                "file",
                relative,
                "unknown",
                {
                    "path": relative,
                    "module": index.by_path[relative],
                    "kind": "main_guard",
                    "line": ast_node.lineno,
                    "launchers": 0,
                    "activation": (
                        "administrative_on_demand" if administrative else "runtime"
                    ),
                    "activation_evidence": (
                        "argparse --apply gate + rollback option"
                        if administrative
                        else "main_guard_only"
                    ),
                },
            )
            break

    for launcher, target, evidence in _iter_launchers(root, index):
        node_id = f"entrypoint:{target}"
        existing = nodes.get(node_id)
        metadata = (
            dict(existing.metadata)
            if existing
            else {
                "path": target,
                "module": index.by_path.get(target, target),
                "kind": "launched",
                "launchers": 0,
            }
        )
        launchers = metadata.get("launchers", 0)
        metadata["launchers"] = (launchers if isinstance(launchers, int) else 0) + 1
        nodes[node_id] = GraphNode(node_id, "file", target, "active", metadata)
        launcher_id = f"launcher:{launcher}"
        nodes.setdefault(
            launcher_id,
            GraphNode(launcher_id, "file", launcher, "active", {"path": launcher}),
        )
        edge = GraphEdge(launcher_id, node_id, "launches", evidence)
        if edge not in edges:
            edges.append(edge)

    documented = _documented_paths(root)
    for node_id, graph_node in nodes.items():
        if not node_id.startswith("entrypoint:"):
            continue
        if graph_node.metadata.get("launchers"):
            continue
        # Una herramienta que la documentación explica cómo ejecutar no es
        # código muerto: es manual. Meterla en el mismo saco que un fichero
        # que nadie nombra convierte 45 utilidades vivas en deuda inventada.
        cited = (
            graph_node.label in documented or Path(graph_node.label).name in documented
        )
        nodes[node_id] = GraphNode(
            graph_node.node_id,
            graph_node.kind,
            graph_node.label,
            "legacy" if cited else "disconnected",
            {**graph_node.metadata, "documented": cited},
        )

    return sorted(nodes.values(), key=lambda n: n.node_id), edges


def _administrative_on_demand(tree: ast.Module, relative: str) -> bool:
    """Reconoce herramientas reversibles por su contrato AST, no por su nombre."""
    if not relative.startswith("scripts/"):
        return False
    options: set[str] = set()
    imports_argparse = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports_argparse |= any(alias.name == "argparse" for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports_argparse |= node.module == "argparse"
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr != "add_argument":
                continue
            options.update(
                arg.value
                for arg in node.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            )
    rollback = {"--rollback", "--revert", "--revertir"}
    return imports_argparse and "--apply" in options and bool(options & rollback)


def reachable_modules(
    root: Path,
    index: ModuleIndex | None = None,
    import_edges: list[GraphEdge] | None = None,
) -> set[str]:
    """Módulos alcanzables por imports desde un entrypoint que alguien arranca.

    Un `__main__` prueba que un fichero *puede* ejecutarse; sólo Procfile,
    Dockerfile, systemd, workflows y `[project.scripts]` prueban que alguien lo
    arranca. Se parte de esos y se sigue la cadena de imports.

    Esto es lo que separa «tiene importadores» de «el sistema lo conecta»: un
    módulo importado únicamente por otro que jamás se ejecuta está tan
    denervado como uno que nadie nombra, y la cuenta de importadores no
    distingue los dos casos.
    """
    root = root.resolve()
    index = index or build_module_index(root)
    if import_edges is None:
        _nodes, import_edges = build_import_graph(root, index)

    adjacency: dict[str, set[str]] = {}
    for edge in import_edges:
        if edge.relation != "imports":
            continue
        source = edge.source.partition(":")[2]
        adjacency.setdefault(source, set()).add(edge.target.partition(":")[2])

    entry_nodes, _entry_edges = build_entrypoint_graph(root, index)
    pending = [
        str(node.metadata.get("path") or "")
        for node in entry_nodes
        if isinstance((launchers := node.metadata.get("launchers")), int)
        and launchers > 0
    ]
    reached = {path for path in pending if path}
    queue = list(reached)
    while queue:
        current = queue.pop()
        for target in adjacency.get(current, ()):
            if target not in reached:
                reached.add(target)
                queue.append(target)
    return reached


def _documented_paths(root: Path) -> set[str]:
    """Rutas y nombres de fichero citados en documentación o workflows."""
    blob: list[str] = []
    for pattern in ("*.md", "docs/**/*.md", ".github/**/*.yml", ".github/**/*.yaml"):
        for path in sorted(root.glob(pattern)):
            try:
                blob.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    text = "\n".join(blob)
    return {token for token in re.findall(r"[\w./-]+\.py", text)} | {
        Path(token).name for token in re.findall(r"[\w./-]+\.py", text)
    }


def _is_main_guard(test: ast.expr) -> bool:
    if not isinstance(test, ast.Compare) or not isinstance(test.left, ast.Name):
        return False
    if test.left.id != "__name__":
        return False
    return any(
        isinstance(c, ast.Constant) and c.value == "__main__" for c in test.comparators
    )


def _iter_launchers(root: Path, index: ModuleIndex) -> Iterator[tuple[str, str, str]]:
    """Extrae (lanzador, fichero lanzado, evidencia) de la configuración real."""
    sources: list[Path] = []
    for pattern in _LAUNCH_CONFIG_GLOBS:
        sources.extend(sorted(root.glob(pattern)))
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        sources.append(pyproject)

    for source in sources:
        if not source.is_file():
            continue
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        launcher = source.relative_to(root).as_posix()
        for launch_pattern in (_MODULE_LAUNCH, _UVICORN_LAUNCH):
            for match in launch_pattern.finditer(text):
                resolved = index.resolve(match.group(1))
                if resolved:
                    yield launcher, resolved, f"{launcher}: {match.group(0).strip()}"
        for match in _SCRIPT_LAUNCH.finditer(text):
            candidate = match.group(1).lstrip("./")
            if candidate in index.by_path:
                yield launcher, candidate, f"{launcher}: {match.group(0).strip()}"
        if source.name == "pyproject.toml":
            for match in re.finditer(
                r'^\s*[\w-]+\s*=\s*"([\w.]+):\w+"', text, re.MULTILINE
            ):
                resolved = index.resolve(match.group(1))
                if resolved:
                    yield launcher, resolved, f"{launcher}: {match.group(0).strip()}"

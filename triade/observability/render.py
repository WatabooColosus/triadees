"""Renderizado legible de los grafos: DOT, Mermaid y Markdown.

El color no decora: codifica el estado verificado del nodo. Un nodo rojo es una
ruta desconectada demostrada, no una opinión. La misma paleta se usa en los tres
formatos y en el explorador interactivo, para que un nodo signifique lo mismo
mires donde mires.
"""

from __future__ import annotations

from pathlib import Path

from .contracts import GraphEdge, GraphNode

#: estado verificado → (color de relleno, borde, significado)
STATE_COLORS: dict[str, tuple[str, str, str]] = {
    "active": ("#1b7f4b", "#0d3f25", "conectado y con ejecución demostrada"),
    "legacy": ("#b8860b", "#6b4f06", "existe y se usó, sin actividad reciente"),
    "disconnected": ("#b03030", "#5c1818", "sin lector, sin caller o sin ejecución"),
    "failed": ("#7a1f1f", "#3d0f0f", "falló en ejecución real"),
    "protected": ("#5b3fa8", "#2e2054", "secreto: identidad enmascarada"),
    "hidden": ("#41637a", "#22333d", "oculto pero inventariado"),
    "unknown": ("#5a5a5a", "#2d2d2d", "sin evidencia suficiente"),
}
_DEFAULT_COLOR = STATE_COLORS["unknown"]


def color_for(state: str) -> str:
    """Color de relleno del estado. Es la fuente única para UI y exportaciones."""
    return STATE_COLORS.get(state, _DEFAULT_COLOR)[0]


def legend() -> list[dict[str, str]]:
    return [
        {"state": state, "color": fill, "border": border, "meaning": meaning}
        for state, (fill, border, meaning) in STATE_COLORS.items()
    ]


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _safe_id(node_id: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in node_id)


def to_dot(nodes: list[GraphNode], edges: list[GraphEdge], *, graph_type: str) -> str:
    lines = [
        f'digraph "{_escape(graph_type)}" {{',
        "  rankdir=LR;",
        '  node [style="filled,rounded", shape=box, fontcolor=white, fontname=Helvetica];',
        '  edge [color="#8a8a8a", fontsize=9];',
    ]
    for node in nodes:
        fill, border, _ = STATE_COLORS.get(node.state, _DEFAULT_COLOR)
        lines.append(
            f'  "{_escape(node.node_id)}" [label="{_escape(node.label)}", '
            f'fillcolor="{fill}", color="{border}", tooltip="{_escape(node.state)}"];'
        )
    for edge in edges:
        lines.append(
            f'  "{_escape(edge.source)}" -> "{_escape(edge.target)}" '
            f'[label="{_escape(edge.relation)}"];'
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def to_mermaid(
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    *,
    graph_type: str,
    max_nodes: int = 120,
) -> str:
    """Mermaid para lectura humana.

    Un grafo de miles de nodos no se lee: por encima de `max_nodes` se recorta y
    el recorte se declara en el propio diagrama, nunca en silencio.
    """
    shown = nodes[:max_nodes]
    visible = {node.node_id for node in shown}
    lines = [f"%% {graph_type}", "graph LR"]
    for node in shown:
        lines.append(f'  {_safe_id(node.node_id)}["{node.label}"]:::{node.state}')
    for edge in edges:
        if edge.source in visible and edge.target in visible:
            lines.append(
                f"  {_safe_id(edge.source)} -->|{edge.relation}| {_safe_id(edge.target)}"
            )
    for state, (fill, border, _) in STATE_COLORS.items():
        lines.append(f"  classDef {state} fill:{fill},stroke:{border},color:#fff;")
    if len(nodes) > max_nodes:
        lines.append(
            f"  %% recorte declarado: {len(shown)} de {len(nodes)} nodos mostrados"
        )
    return "\n".join(lines) + "\n"


def to_markdown(
    nodes: list[GraphNode], edges: list[GraphEdge], *, graph_type: str
) -> str:
    counts: dict[str, int] = {}
    for node in nodes:
        counts[node.state] = counts.get(node.state, 0) + 1
    lines = [
        f"# Grafo `{graph_type}`",
        "",
        f"- Nodos: {len(nodes)}",
        f"- Aristas: {len(edges)}",
        "",
        "## Estados",
        "",
        "| Estado | Nodos | Significado |",
        "|---|---:|---|",
    ]
    for state in sorted(counts, key=lambda s: -counts[s]):
        meaning = STATE_COLORS.get(state, _DEFAULT_COLOR)[2]
        lines.append(f"| `{state}` | {counts[state]} | {meaning} |")
    disconnected = [n for n in nodes if n.state == "disconnected"]
    if disconnected:
        lines += [
            "",
            f"## Nodos desconectados ({len(disconnected)})",
            "",
            "| Nodo | Etiqueta | Metadatos |",
            "|---|---|---|",
        ]
        for node in disconnected[:200]:
            meta = ", ".join(f"{k}={v}" for k, v in sorted(node.metadata.items()))
            lines.append(f"| `{node.node_id}` | {node.label} | {meta} |")
        if len(disconnected) > 200:
            lines.append(f"| … | {len(disconnected) - 200} más | recorte declarado |")
    return "\n".join(lines) + "\n"


def write_renderings(
    output: Path,
    stem: str,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    *,
    graph_type: str,
) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for suffix, payload in (
        (".dot", to_dot(nodes, edges, graph_type=graph_type)),
        (".mmd", to_mermaid(nodes, edges, graph_type=graph_type)),
        (".md", to_markdown(nodes, edges, graph_type=graph_type)),
    ):
        path = output / f"{stem}{suffix}"
        path.write_text(payload, encoding="utf-8")
        written.append(path)
    return written

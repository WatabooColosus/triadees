"""Lectura de los grafos por parte de la propia Tríade.

Los grafos no sirven de nada si sólo los mira un auditor externo: serían otra
tabla que se escribe y nadie lee. Este módulo los convierte en un informe de
deuda que el runtime puede consumir para decidir en qué trabajar.

El coste manda el diseño. Reconstruir el AST completo cuesta ~45 s, así que los
artefactos se reutilizan mientras estén frescos y sólo se regeneran cuando
caducan. Las señales de SQLite, en cambio, se leen siempre: son las que cambian
entre dos ciclos del worker.

No hay porcentajes globales. Cada cifra es un recuento con su lista de ejemplos
y la evidencia que la sostiene.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .runtime_graph import (
    VITAL_CHAIN,
    live_table_counts,
    open_readonly,
    recent_activity,
    task_type_counts,
)

DEFAULT_CACHE = Path("artifacts/internal_graphs")
#: Seis horas: la estructura del repositorio no cambia sola entre despliegues,
#: y regenerarla en cada ciclo del worker costaría más que el trabajo que evalúa.
DEFAULT_MAX_AGE_SECONDS = 6 * 60 * 60
#: Cuántos ejemplos acompañan a cada recuento. Suficiente para actuar, no tanto
#: como para llenar la Bodega de ruido.
SAMPLE = 10


def _is_fresh(cache_dir: Path, max_age_seconds: float) -> bool:
    index = cache_dir / "index.json"
    if not index.exists():
        return False
    return (time.time() - index.stat().st_mtime) < max_age_seconds


def _load(cache_dir: Path, stem: str) -> dict[str, Any] | None:
    path = cache_dir / f"{stem}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ensure_graphs(
    root: Path,
    db_path: Path | None,
    cache_dir: Path = DEFAULT_CACHE,
    *,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    allow_build: bool = True,
) -> bool:
    """Deja los artefactos disponibles y frescos. Devuelve si hay algo que leer.

    Con `allow_build=False` no se regenera nada: sirve para consultas que
    prefieren un informe vacío antes que pagar un escaneo completo.
    """
    if _is_fresh(cache_dir, max_age_seconds):
        return True
    if not allow_build:
        return (cache_dir / "index.json").exists()
    # Import local: `build_all` arrastra todos los constructores y este módulo
    # se importa desde el worker, donde el arranque debe ser barato.
    from scripts.build_internal_graphs import build_all

    build_all(root, db_path, cache_dir, render=False)
    return True


def build_debt_report(
    root: Path,
    db_path: Path | None = None,
    cache_dir: Path = DEFAULT_CACHE,
    *,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    allow_build: bool = True,
) -> dict[str, Any]:
    """Deuda estructural real, lista para que el runtime decida sobre ella.

    Cada entrada lleva `count`, `sample` y `evidence`: el recuento para priorizar,
    los ejemplos para empezar, y de dónde salió cada cosa para poder discutirla.
    """
    available = ensure_graphs(
        root,
        db_path,
        cache_dir,
        max_age_seconds=max_age_seconds,
        allow_build=allow_build,
    )
    if not available:
        return {
            "status": "unknown",
            "reason": "no hay grafos generados y no se permitió construirlos",
            "items": {},
            "simulated": False,
        }

    items: dict[str, Any] = {}
    generated_at = (cache_dir / "index.json").stat().st_mtime

    # Lo estructural viene del artefacto; los recuentos que cambian entre ciclos
    # —ejecuciones y filas— se leen siempre de SQLite. Si no se separaran, un
    # informe de hace seis horas diría que una tarea nunca corrió cuando acaba
    # de hacerlo.
    connection = open_readonly(db_path)
    try:
        rows_by_table = live_table_counts(connection) if connection else {}
    finally:
        if connection is not None:
            connection.close()
    executions = task_type_counts(db_path)
    live_db = bool(rows_by_table)

    workers = _load(cache_dir, "worker_graph")
    if workers:
        declared = [
            n["label"]
            for n in workers["nodes"]
            if n["node_id"].startswith("task_type:")
        ]
        idle = [t for t in declared if executions.get(t, 0) == 0] if live_db else []
        items["task_types_never_executed"] = _entry(
            idle,
            "worker_graph.json para los tipos declarados; ejecuciones leídas en vivo",
        )

    tables = _load(cache_dir, "table_graph")
    if tables:
        nodes = [n for n in tables["nodes"] if n["node_id"].startswith("table:")]
        write_only, never_written = [], []
        for node in nodes:
            rows = rows_by_table.get(node["label"])
            if rows is None:
                continue
            readers = node["metadata"].get("readers", 0)
            writers = node["metadata"].get("writers", 0)
            if rows > 0 and readers == 0 and writers > 0:
                write_only.append(node["label"])
            elif rows == 0 and writers > 0:
                never_written.append(node["label"])
        items["tables_written_never_read"] = _entry(
            write_only,
            "table_graph.json para lectores y escritores; filas leídas en vivo",
        )
        items["tables_with_writer_and_no_rows"] = _entry(
            never_written,
            "table_graph.json para escritores; filas leídas en vivo",
        )

    imports = _load(cache_dir, "import_graph")
    if imports:
        orphans = [
            n["metadata"]["path"]
            for n in imports["nodes"]
            if n["state"] == "disconnected"
            and str(n["metadata"].get("path", "")).startswith(("triade/", "apps/"))
        ]
        items["modules_without_importer"] = _entry(
            orphans, "import_graph.json: módulo de producción que nadie importa"
        )

    entrypoints = _load(cache_dir, "entrypoint_graph")
    if entrypoints:
        unlaunched = [
            n["label"]
            for n in entrypoints["nodes"]
            if n["node_id"].startswith("entrypoint:") and n["state"] == "disconnected"
        ]
        items["entrypoints_without_launcher"] = _entry(
            unlaunched, "entrypoint_graph.json: guard __main__ que nadie arranca"
        )

    items["vital_chain_gaps"] = _vital_chain_gaps(db_path)

    total = sum(entry["count"] for entry in items.values())
    return {
        "status": "measured",
        # Fórmula explícita: suma de los recuentos de cada categoría. No es un
        # porcentaje ni una nota; es cuántas cosas concretas hay que mirar.
        "debt_items_total": total,
        "formula": "debt_items_total = suma de count de cada categoría",
        "graphs_generated_at": generated_at,
        "graphs_age_seconds": round(time.time() - generated_at, 1),
        "items": items,
        "simulated": False,
    }


def _entry(values: list[str], evidence: str) -> dict[str, Any]:
    return {
        "count": len(values),
        "sample": sorted(values)[:SAMPLE],
        "evidence": evidence,
    }


def _vital_chain_gaps(db_path: Path | None) -> dict[str, Any]:
    """Eslabones de la cadena vital sin filas o sin actividad reciente.

    Se lee siempre de SQLite, nunca del artefacto: es justo lo que cambia entre
    dos ciclos del worker, y un informe de deuda con un latido de hace seis
    horas describiría un sistema que ya no existe.
    """
    connection = open_readonly(db_path)
    if connection is None:
        return {"count": 0, "sample": [], "evidence": "sin base viva: NEEDS_EVIDENCE"}
    try:
        rows_by_table = live_table_counts(connection)
        fresh = recent_activity(
            connection, [t for _, _, tables in VITAL_CHAIN for t in tables]
        )
    finally:
        connection.close()

    gaps: list[str] = []
    for stage, _anchors, tables in VITAL_CHAIN:
        present = [t for t in tables if t in rows_by_table]
        total = sum(rows_by_table.get(t, 0) for t in present)
        if total == 0:
            gaps.append(f"{stage}: sin filas en {', '.join(tables)}")
        elif not any(fresh.get(t) for t in present):
            gaps.append(f"{stage}: {total} filas, ninguna en 24 h")
    return {
        "count": len(gaps),
        "sample": gaps[:SAMPLE],
        "evidence": "SQLite en mode=ro sobre las tablas de cada eslabón",
    }


def summarise_for_humans(report: dict[str, Any]) -> str:
    """Una línea por categoría con deuda. Es lo que acaba en Qualia y en eventos."""
    if report.get("status") != "measured":
        return f"Deuda no medible: {report.get('reason', 'desconocido')}"
    parts = [
        f"{name.replace('_', ' ')}: {entry['count']}"
        for name, entry in sorted(report["items"].items())
        if entry["count"]
    ]
    if not parts:
        return "Sin deuda estructural detectable en los grafos internos."
    return "Deuda estructural medida en los grafos internos · " + " · ".join(parts)


def unexecuted_task_types(report: dict[str, Any]) -> list[str]:
    """Atajo para quien quiera actuar sobre la deuda, no sólo describirla."""
    entry = report.get("items", {}).get("task_types_never_executed")
    return list(entry["sample"]) if entry else []

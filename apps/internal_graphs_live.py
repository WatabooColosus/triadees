"""Lectura viva y no destructiva de los grafos internos de Tríade Ω.

Sirve los siete grafos verificables como observabilidad en tiempo real: cada
nodo llega con su estado, su color y la evidencia que lo justifica, para que el
explorador pueda pintarlo y abrirlo sin volver a interpretarlo por su cuenta.

Todo sale del filesystem, del proceso vivo y de SQLite en `mode=ro`. Nada se
escribe. Cuando algo no puede comprobarse, viaja como `unknown`, nunca como un
valor inventado.
"""

from __future__ import annotations

import json
import os
import resource
import shutil
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any

from triade.db import sqlite3
from triade.observability.code_graph import (
    build_call_graph,
    build_entrypoint_graph,
    build_import_graph,
    build_module_index,
)
from triade.observability.event_feed import (
    FeedCursor,
    latest_cursor,
    read_new_events,
    read_recent_events,
)
from triade.observability.file_graph import build_file_graph
from triade.observability.neural_graph import build_neural_graph
from triade.observability.refresh import GraphRefresher
from triade.observability.render import color_for, legend
from triade.observability.runtime_graph import (
    VITAL_CHAIN,
    build_organ_graph,
    build_table_graph,
    build_vital_chain_graph,
    build_worker_graph,
    literal_strings,
    live_table_counts,
    open_readonly,
    recent_activity,
    task_type_counts,
    task_type_recency,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "triade" / "memory" / "triade.db"

#: Grafos servidos por la API. El orden es el del recorrido: del cuerpo físico
#: al organismo, y de ahí a la cadena que demuestra que sigue vivo.
GRAPH_BUILDERS = (
    "physical",
    "system",
    "imports",
    "calls",
    "entrypoints",
    "workers",
    "tables",
    "organs",
    "vital_chain",
    "neural",
)
#: Los grafos caros se recalculan como mucho cada este intervalo. La estructura
#: del repositorio no cambia entre dos peticiones seguidas; el runtime sí.
_STRUCTURAL_TTL_SECONDS = 60.0
#: Sólo el grafo neural sale entero de SQLite; los demás requieren releer el AST
#: del repositorio completo, que cuesta segundos y no puede ir en cada pulso.
_LIVE_GRAPHS = {"neural"}

_cache: dict[str, tuple[float, dict[str, Any]]] = {}

_SYSTEM_COMPONENTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "INPUT": ("entrypoints", ("entrypoint:",)),
    "HYPOTHALAMUS": ("calls", ("hypothalam",)),
    "CENTRAL": ("calls", ("central",)),
    "ROUTING": ("calls", ("rout",)),
    "MODELS": ("imports", ("model", "ollama")),
    "MEMORY": ("tables", ("memory", "semantic", "episodic")),
    "GOALS": ("tables", ("goal", "planning_graph")),
    "WORKERS": ("workers", ("worker", "task_type:")),
    "LEARNING": ("tables", ("learning", "education")),
    "IMPROVEMENT": ("tables", ("improvement", "canar")),
    "NEURONS": ("neural", ("neuron",)),
    "FEDERATION": ("tables", ("federat",)),
    "SAFETY": ("imports", ("safety", "constitution")),
    "OBSERVABILITY": ("imports", ("observability", "internal_graph")),
}

_SYSTEM_FLOW = (
    ("INPUT", "HYPOTHALAMUS"),
    ("HYPOTHALAMUS", "CENTRAL"),
    ("CENTRAL", "ROUTING"),
    ("ROUTING", "MODELS"),
    ("ROUTING", "MEMORY"),
    ("ROUTING", "GOALS"),
    ("GOALS", "WORKERS"),
    ("WORKERS", "LEARNING"),
    ("LEARNING", "MEMORY"),
    ("LEARNING", "IMPROVEMENT"),
    ("IMPROVEMENT", "NEURONS"),
    ("WORKERS", "FEDERATION"),
    ("SAFETY", "ROUTING"),
    ("OBSERVABILITY", "WORKERS"),
    ("OBSERVABILITY", "LEARNING"),
)


def _db_path() -> Path:
    value = os.getenv("TRIADE_DB_PATH", str(DEFAULT_DB))
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _resource_snapshot() -> dict[str, Any]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    disk = shutil.disk_usage(ROOT)
    load = list(os.getloadavg()) if hasattr(os, "getloadavg") else []
    return {
        "pid": os.getpid(),
        "process_cpu_seconds": round(usage.ru_utime + usage.ru_stime, 4),
        "process_max_rss_kb": int(usage.ru_maxrss),
        "load_average": load,
        "disk_total": disk.total,
        "disk_used": disk.used,
        "disk_free": disk.free,
    }


def _database_health(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": "unavailable", "integrity": "unknown"}
    result: dict[str, Any] = {
        "exists": True,
        "path": "protected",
        "size": path.stat().st_size,
        "integrity": "unknown",
        "tables": 0,
    }
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
    try:
        result["integrity"] = connection.execute("PRAGMA quick_check").fetchone()[0]
        result["tables"] = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
    finally:
        connection.close()
    return result


def _serialise(nodes: list[Any], edges: list[Any], *, kind: str) -> dict[str, Any]:
    """Empaqueta un grafo con el color ya resuelto por estado."""
    payload_nodes = []
    for node in nodes:
        item = asdict(node)
        item["color"] = color_for(node.state)
        payload_nodes.append(item)
    counts: dict[str, int] = {}
    for node in nodes:
        counts[node.state] = counts.get(node.state, 0) + 1
    return {
        "graph": kind,
        "nodes": payload_nodes,
        "edges": [asdict(edge) for edge in edges],
        "states": counts,
        "simulated": False,
    }


#: Nombre servido → artefacto en disco. El generador, el supervisor, CI y esta
#: API leen exactamente los mismos ficheros: un solo grafo, cuatro consumidores.
ARTIFACT_STEMS = {
    "physical": "file_graph",
    "imports": "import_graph",
    "calls": "call_graph",
    "entrypoints": "entrypoint_graph",
    "workers": "worker_graph",
    "tables": "table_graph",
    "organs": "organ_graph",
    "vital_chain": "vital_chain_graph",
    "neural": "neural_graph",
}
ARTIFACT_DIR = ROOT / "artifacts" / "internal_graphs"
#: Seis horas, igual que la introspección interna. Es la misma pregunta.
_ARTIFACT_MAX_AGE_SECONDS = 6 * 60 * 60

#: Un único refrescador para todo el proceso: las rutas de grafo y la de deuda
#: leen los mismos ficheros, así que tienen que compartir también quién los
#: reconstruye. Dos refrescadores serían dos escaneos simultáneos de 53 s.
REFRESHER = GraphRefresher(ROOT, ARTIFACT_DIR, _db_path())


def refresh_artifacts(*, force: bool = False) -> str:
    """Lanza la reconstrucción en segundo plano si el artefacto ha caducado.

    Se llama desde cada lectura y no espera: quien pregunta recibe lo que hay
    ahora, con su edad declarada, y la respuesta siguiente ya trae lo nuevo.
    """
    return REFRESHER.request(force=force)


def _from_artifact(name: str) -> dict[str, Any] | None:
    """Reutiliza el grafo ya generado si sigue fresco.

    Construirlo en caliente cuesta hasta 45 s de AST, y durante ese tiempo la
    página no muestra nada: parece rota. El artefacto ya existe —lo escribe el
    generador y lo sube CI— así que se sirve tal cual y se recalcula sólo
    cuando caduca.
    """
    path = ARTIFACT_DIR / f"{ARTIFACT_STEMS[name]}.json"
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > _ARTIFACT_MAX_AGE_SECONDS:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    nodes = payload.get("nodes") or []
    counts: dict[str, int] = {}
    for node in nodes:
        state = str(node.get("state", "unknown"))
        node["color"] = color_for(state)
        counts[state] = counts.get(state, 0) + 1
    return {
        "graph": name,
        "nodes": nodes,
        "edges": payload.get("edges") or [],
        "states": counts,
        "source": "artifact",
        "generated_at": path.stat().st_mtime,
        "simulated": False,
    }


def _build_system_graph() -> dict[str, Any]:
    """Macro recorrido derivado de nodos que existen en los grafos canónicos."""
    nodes: list[dict[str, Any]] = []
    present: set[str] = set()
    for component, (graph_name, needles) in _SYSTEM_COMPONENTS.items():
        graph = build_graph(graph_name)
        matches = [
            node
            for node in graph["nodes"]
            if any(
                needle in f"{node.get('node_id', '')} {node.get('label', '')}".lower()
                for needle in needles
            )
        ]
        if not matches:
            continue
        states: dict[str, int] = {}
        for match in matches:
            state = str(match.get("state") or "unknown")
            states[state] = states.get(state, 0) + 1
        state = (
            "active"
            if states.get("active")
            else "failed"
            if states.get("failed")
            else "legacy"
            if states.get("legacy")
            else "disconnected"
            if states.get("disconnected")
            else "unknown"
        )
        present.add(component)
        nodes.append(
            {
                "node_id": f"system:{component.lower()}",
                "kind": "subsystem",
                "label": component,
                "state": state,
                "color": color_for(state),
                "metadata": {
                    "source_graph": graph_name,
                    "matched_nodes": len(matches),
                    "states": states,
                    "evidence_nodes": [m.get("node_id") for m in matches[:12]],
                    "progressive_view": graph_name,
                },
            }
        )
    edges = [
        {
            "source": f"system:{source.lower()}",
            "target": f"system:{target.lower()}",
            "relation": "causal_flow",
            "evidence": (
                f"internal_graphs:{_SYSTEM_COMPONENTS[source][0]}"
                f"→{_SYSTEM_COMPONENTS[target][0]}"
            ),
            "metadata": {"progressive": True},
        }
        for source, target in _SYSTEM_FLOW
        if source in present and target in present
    ]
    state_counts: dict[str, int] = {}
    for node in nodes:
        state_counts[node["state"]] = state_counts.get(node["state"], 0) + 1
    return {
        "graph": "system",
        "nodes": nodes,
        "edges": edges,
        "states": state_counts,
        "source": "canonical_graph_aggregation",
        "refresh": REFRESHER.status(),
        "simulated": False,
    }


def build_graph(name: str, *, limit: int | None = None) -> dict[str, Any]:
    """Sirve un grafo por nombre: artefacto fresco si lo hay, si no lo construye."""
    if name not in GRAPH_BUILDERS:
        raise KeyError(f"Grafo desconocido: {name}")
    now = time.time()
    cached = _cache.get(name)
    if (
        cached
        and name not in _LIVE_GRAPHS
        and now - cached[0] < _STRUCTURAL_TTL_SECONDS
    ):
        # El grafo cacheado puede repetirse un minuto; su estado de refresco no,
        # porque de él depende que la interfaz sepa si debe volver a preguntar.
        cached[1]["refresh"] = REFRESHER.status()
        return cached[1]

    if name == "system":
        payload = _build_system_graph()
        _cache[name] = (now, payload)
        return payload

    if name not in _LIVE_GRAPHS:
        # Se pide la regeneración antes de servir, no después: si el artefacto
        # está caducado, esta respuesta sale vieja pero declarada, y la próxima
        # ya lee lo nuevo sin que nadie haya esperado 53 s.
        refresh_artifacts()
        artifact = _from_artifact(name)
        if artifact is not None:
            artifact["refresh"] = REFRESHER.status()
            _cache[name] = (now, artifact)
            return artifact

    db_path = _db_path()
    index = build_module_index(ROOT)
    if name == "physical":
        nodes, edges = build_file_graph(ROOT)
    elif name == "imports":
        nodes, edges = build_import_graph(ROOT, index)
    elif name == "calls":
        nodes, edges = build_call_graph(ROOT, index)
    elif name == "entrypoints":
        nodes, edges = build_entrypoint_graph(ROOT, index)
    elif name == "workers":
        nodes, edges = build_worker_graph(ROOT, index, db_path)
    elif name == "tables":
        nodes, edges = build_table_graph(ROOT, index, db_path)
    elif name == "organs":
        nodes, edges = build_organ_graph(ROOT, index, db_path)
    elif name == "vital_chain":
        nodes, edges = build_vital_chain_graph(ROOT, index, db_path)
    else:
        nodes, edges = build_neural_graph(db_path, limit=limit or 5000)

    if limit is not None and len(nodes) > limit:
        allowed = {node.node_id for node in nodes[:limit]}
        nodes = nodes[:limit]
        edges = [e for e in edges if e.source in allowed and e.target in allowed]

    payload = _serialise(nodes, edges, kind=name)
    _cache[name] = (now, payload)
    return payload


def node_detail(graph: str, node_id: str) -> dict[str, Any]:
    """Interior de un nodo: sus metadatos y todas sus aristas con evidencia.

    Es lo que convierte el grafo en introspección y no en un dibujo: desde
    cualquier nodo se puede llegar a la línea de código o a la tabla que lo
    respalda.
    """
    payload = build_graph(graph)
    node = next((n for n in payload["nodes"] if n["node_id"] == node_id), None)
    if node is None:
        raise KeyError(f"Nodo desconocido en {graph}: {node_id}")
    outgoing = [e for e in payload["edges"] if e["source"] == node_id]
    incoming = [e for e in payload["edges"] if e["target"] == node_id]
    return {
        "graph": graph,
        "node": node,
        "outgoing": outgoing,
        "incoming": incoming,
        "degree": {"out": len(outgoing), "in": len(incoming)},
        "simulated": False,
    }


def build_live_snapshot(
    *, file_limit: int | None = None, neural_limit: int = 5000
) -> dict[str, Any]:
    """Snapshot construido únicamente desde filesystem, SQLite y proceso reales."""
    physical = build_graph("physical", limit=file_limit)
    neural = build_graph("neural", limit=neural_limit)
    db_path = _db_path()
    return {
        "schema_version": 3,
        "generated_at": time.time(),
        "source": {
            "filesystem": str(ROOT.name),
            "database": "sqlite-read-only",
            "runtime": "current-python-process",
            "simulated": False,
        },
        "physical": {"nodes": physical["nodes"], "edges": physical["edges"]},
        "neural": {"nodes": neural["nodes"], "edges": neural["edges"]},
        "legend": legend(),
        "resources": _resource_snapshot(),
        "database": _database_health(db_path),
    }


def build_signals() -> dict[str, Any]:
    """Señales vivas: sólo lo que cambia mientras el runtime trabaja.

    La estructura —qué módulos hay, quién llama a quién— no cambia entre dos
    pulsos, y releerla cuesta segundos de AST. Lo que sí cambia cada pocos
    segundos son las filas de SQLite: tareas ejecutadas, eslabones con
    actividad, tablas que crecen. Esto lee exactamente eso y nada más, de forma
    que el explorador puede repintar el estado de cada nodo en caliente.
    """
    db_path = _db_path()
    connection = open_readonly(db_path)
    try:
        rows_by_table = live_table_counts(connection)
        chain_tables = [t for _, _, tables in VITAL_CHAIN for t in tables]
        recent = recent_activity(connection, chain_tables)
    finally:
        if connection is not None:
            connection.close()

    available = bool(rows_by_table)
    stages: dict[str, Any] = {}
    for stage, _anchors, tables in VITAL_CHAIN:
        present = [t for t in tables if t in rows_by_table]
        total = sum(rows_by_table.get(t, 0) for t in present)
        fresh = any(recent.get(t) for t in present)
        # El eslabón tiene código: eso ya lo demostró el grafo estructural. Aquí
        # sólo se decide si además está latiendo ahora mismo.
        state = (
            "unknown"
            if not available
            else "disconnected"
            if total == 0
            else "active"
            if fresh
            else "legacy"
        )
        stages[stage] = {
            "rows": total if available else "UNKNOWN",
            "recent_24h": fresh if available else "UNKNOWN",
            "state": state,
        }

    executions = task_type_counts(db_path)
    # La cuenta suma `worker_tasks`, congelada desde el 2026-07-29. Sin la fecha,
    # un tipo que no corre desde hace días late en verde igual que uno que acaba
    # de ejecutarse: el mismo estado que ya distinguen los eslabones de arriba.
    recent = task_type_recency(db_path)
    # `ready_when_idle` sale del grafo de workers ya generado y **no** se
    # recalcula aquí: verificar los contratos de activación cuesta una lectura
    # completa del AST, que es justo lo que este latido evita.
    #
    # El precio es que depende de un artefacto que puede no existir —`artifacts/`
    # está en `.gitignore`, así que en CI no está—. Cuando falta, esto ponía el
    # conjunto vacío y seguía: un tipo humano-gateado como `goal_lora_train`
    # salía `disconnected`, o sea «no está conectado», cuando la verdad es «no
    # lo sé, no he podido mirarlo». Afirmar desconexión sin evidencia es
    # exactamente lo que este grafo existe para no hacer, y encima hacía que la
    # prueba fuera verde en local —donde el fichero sí está— y roja en CI.
    ready_when_idle: set[str] = set()
    worker_artifact = ARTIFACT_DIR / "worker_graph.json"
    try:
        worker_nodes = json.loads(worker_artifact.read_text(encoding="utf-8")).get(
            "nodes", []
        )
        readiness_known = True
    except (OSError, ValueError, AttributeError):
        worker_nodes = []
        readiness_known = False
    for node in worker_nodes:
        metadata = node.get("metadata") or {}
        if metadata.get("ready_when_idle"):
            ready_when_idle.add(str(node.get("label") or ""))
    # Los tipos que nunca se ejecutaron no aparecen en la cola, y son justo los
    # que hay que ver: se parten de los declarados, no de los encontrados.
    declared = literal_strings(ROOT, "triade/workers/contracts.py", "WorkerTaskType")
    task_types = {
        task_type: {
            "executions": executions.get(task_type, 0) if available else "UNKNOWN",
            "recent_24h": recent.get(task_type, False) if available else "UNKNOWN",
            "state": (
                "unknown"
                if not available
                else "active"
                if recent.get(task_type, False)
                else "ready"
                if task_type in ready_when_idle
                else "legacy"
                if executions.get(task_type, 0) > 0
                # Sin ejecuciones y sin poder consultar el readiness, lo honesto
                # es `unknown`, no `disconnected`.
                else "disconnected"
                if readiness_known
                else "unknown"
            ),
        }
        for task_type in sorted(set(declared) | set(executions))
    }
    return {
        "stages": stages,
        "task_types": task_types,
        "tables": rows_by_table,
        # De dónde salió el readiness, para que quien lea el latido sepa si un
        # `unknown` es ignorancia del sistema o falta del artefacto.
        "readiness_source": "worker_graph_artifact" if readiness_known else "missing",
        "simulated": False,
    }


def build_pulse(cursor: FeedCursor | None = None) -> tuple[dict[str, Any], FeedCursor]:
    """Latido del stream: acciones ocurridas, señales, recursos y salud.

    Las acciones son lo que hace que el grafo se mueva solo en vez de limitarse
    a informar. Se leen por cursor, así que entre dos pulsos no se pierde
    ninguna aunque el cliente tarde o el proceso se reinicie.
    """
    db_path = _db_path()
    cursor = cursor if cursor is not None else latest_cursor(db_path)
    events, advanced = read_new_events(db_path, cursor)
    payload = {
        "schema_version": 4,
        "generated_at": time.time(),
        "events": events,
        "cursor": advanced.to_dict(),
        "signals": build_signals(),
        "legend": legend(),
        "resources": _resource_snapshot(),
        "database": _database_health(db_path),
        "simulated": False,
    }
    return payload, advanced


def system_health() -> dict[str, Any]:
    """Publica Health Truth sin reinterpretarlo en el navegador."""
    from triade.runtime.service_health import ServiceHealth

    measured = ServiceHealth(_db_path()).inspect(process_running=True).to_dict()
    state_map = {
        "idle": "healthy",
        "critical": "failed",
        "stopped": "failed",
    }
    overall = state_map.get(str(measured["state"]), str(measured["state"]))
    metrics = measured.get("metrics") or {}
    queue = metrics.get("queue") or {}
    ollama = metrics.get("ollama") or {}
    heartbeat_age = metrics.get("heartbeat_age_seconds")
    components = {
        "API": {
            "state": "healthy",
            "evidence": f"process:{os.getpid()}",
            "last_progress": measured["checked_at"],
        },
        "DATABASE": {
            "state": "healthy" if metrics.get("sqlite") == "ok" else "failed",
            "evidence": f"PRAGMA quick_check={metrics.get('sqlite', 'unknown')}",
            "last_progress": measured["checked_at"],
        },
        "MODEL": {
            "state": "healthy"
            if bool(ollama.get("ollama_ok") or ollama.get("ok"))
            else "degraded",
            "evidence": f"ollama:{ollama.get('status') or ollama.get('error_type') or 'unknown'}",
            "last_progress": ollama.get("checked_at"),
        },
        "WORKERS": {
            "state": overall,
            "evidence": (
                f"heartbeat_age_seconds={heartbeat_age}; "
                f"eligible={metrics.get('eligible_pending_tasks', 0)}; "
                f"active={metrics.get('active_tasks', 0)}"
            ),
            "last_progress": metrics.get("last_task_transition_at"),
        },
        "SCHEDULER": {
            "state": overall,
            "evidence": f"queue={json.dumps(queue, sort_keys=True)}",
            "last_progress": metrics.get("last_task_transition_at"),
        },
    }
    return {
        "state": overall,
        "raw_state": measured["state"],
        "reasons": measured["reasons"],
        "checked_at": measured["checked_at"],
        "components": components,
        "metrics": metrics,
        "source": "triade.runtime.service_health.ServiceHealth",
        "simulated": False,
    }


def search_system(query: str, *, limit: int = 30) -> dict[str, Any]:
    """Busca nodos canónicos y devuelve dónde centrarlos, sin duplicarlos."""
    needle = query.strip().lower()
    if not needle:
        return {"query": query, "results": [], "simulated": False}
    results: list[dict[str, Any]] = []
    for graph_name in GRAPH_BUILDERS:
        graph = build_graph(graph_name)
        for node in graph.get("nodes") or []:
            haystack = " ".join(
                (
                    str(node.get("node_id") or ""),
                    str(node.get("label") or ""),
                    json.dumps(node.get("metadata") or {}, ensure_ascii=False),
                )
            ).lower()
            if needle not in haystack:
                continue
            results.append(
                {
                    "graph": graph_name,
                    "node_id": node.get("node_id"),
                    "label": node.get("label"),
                    "kind": node.get("kind"),
                    "state": node.get("state"),
                    "evidence": (node.get("metadata") or {}).get("evidence"),
                }
            )
            if len(results) >= max(1, limit):
                return {"query": query, "results": results, "simulated": False}
    return {"query": query, "results": results, "simulated": False}


def operational_timeline(
    *, limit: int = 100, run_id: str | None = None, task_id: str | None = None
) -> dict[str, Any]:
    return {
        "events": read_recent_events(
            _db_path(), limit=limit, run_id=run_id, task_id=task_id
        ),
        "filters": {"run_id": run_id, "task_id": task_id},
        "simulated": False,
    }


def encode_stream_cursor(cursor: FeedCursor) -> str:
    """Cursor compacto y opaco para el campo ``id`` de Server-Sent Events."""
    raw = json.dumps(cursor.to_dict(), separators=(",", ":"), sort_keys=True).encode()
    return urlsafe_b64encode(raw).decode().rstrip("=")


def decode_stream_cursor(value: str | None) -> FeedCursor | None:
    """Recupera ``Last-Event-ID`` sin confiar en datos enviados por el cliente."""
    if not value or len(value) > 1024:
        return None
    try:
        padding = "=" * (-len(value) % 4)
        raw = json.loads(urlsafe_b64decode(value + padding))
        if not isinstance(raw, dict):
            return None
        positions = {
            str(table): int(position)
            for table, position in raw.items()
            if isinstance(table, str)
            and isinstance(position, int)
            and position >= 0
        }
        if positions.keys() != raw.keys():
            return None
        return FeedCursor.from_dict(positions)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def event_stream(
    interval_seconds: float = 2.0,
    *,
    cursor: FeedCursor | None = None,
    max_lifetime_seconds: float = 8.0,
) -> Iterator[str]:
    """Entrega pulsos SSE en conexiones cortas que se reanudan por cursor.

    El cursor arranca en el presente: quien se conecta ve lo que ocurre desde
    ese momento, no un volcado del historial disfrazado de ahora. Tras ocho
    segundos la conexión termina a propósito y ``EventSource`` reconecta con el
    último ``id``; así Uvicorn no queda retenido por una pestaña durante el
    apagado y tampoco se pierden eventos entre dos conexiones.
    """
    cursor = cursor if cursor is not None else latest_cursor(_db_path())
    started = time.monotonic()
    emitted = 0
    while emitted == 0 or time.monotonic() - started < max_lifetime_seconds:
        try:
            payload, cursor = build_pulse(cursor)
            yield (
                f"id: {encode_stream_cursor(cursor)}\n"
                "event: pulse\n"
                f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
            )
        except (OSError, sqlite3.Error, ValueError) as exc:
            error = {
                "simulated": False,
                "error": type(exc).__name__,
                "detail": str(exc),
            }
            yield f"event: graph_error\ndata: {json.dumps(error, ensure_ascii=False)}\n\n"
        emitted += 1
        if time.monotonic() - started >= max_lifetime_seconds:
            break
        time.sleep(max(1.0, interval_seconds))

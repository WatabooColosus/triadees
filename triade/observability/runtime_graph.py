"""Grafos del organismo en ejecución: workers, tablas, órganos y cadena vital.

La regla es la misma que en `code_graph`: la estructura sale del AST y de las
sentencias SQL escritas en el repositorio. La base viva sólo se abre en
`mode=ro` y únicamente para responder una pregunta que el código no puede
contestar solo — si algo se ejecutó de verdad y cuándo.

Sin base de datos los grafos siguen construyéndose: los nodos quedan con la
evidencia de ejecución en `UNKNOWN`, que es la verdad disponible en ese caso.
"""

from __future__ import annotations

import ast
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from triade.runtime.task_status import ELIGIBLE

from .code_graph import (
    ModuleIndex,
    build_import_graph,
    build_module_index,
    iter_python_files,
    reachable_modules,
)
from .contracts import GraphEdge, GraphNode, NodeState

#: Órgano → prefijos de ruta reales. Un órgano sin carpeta no se dibuja.
ORGAN_PATHS: dict[str, tuple[str, ...]] = {
    "Neurona Central": ("triade/core", "triade/neurons"),
    "Neurona Creadora": ("triade/neuron_factory",),
    "Neurona Educadora": ("triade/training", "triade/evaluation"),
    "Hipotálamo": ("triade/hypothalamus",),
    "Bodega": ("triade/memory", "triade/knowledge"),
    "Cristal": ("triade/consciousness", "triade/constitution"),
    "Qualia": ("triade/qualia",),
    "Workers": ("triade/workers", "triade/runtime"),
    "Learning": ("triade/learning", "triade/self_improvement", "triade/evolution"),
    "Ollama Blood": ("triade/models", "triade/services"),
    "Federación": ("triade/federation",),
    "Unidad 01": ("triade/validation", "triade/verification", "triade/regression"),
}

#: Cadena vital exigida. Cada eslabón se ancla a símbolos y tablas reales.
VITAL_CHAIN: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("LIFE_PULSE", ("LIFE_PULSE", "life_pulse", "pulse_check"), ("metabolic_cycle",)),
    ("necesidad", ("need", "necesidad", "detect_need"), ("metabolic_needs",)),
    ("plan", ("plan", "planner", "mission"), ("planning_graph", "neuron_missions")),
    ("tarea", ("task", "tarea"), ("autonomous_tasks", "worker_tasks")),
    ("cola", ("queue", "cola", "claim"), ("worker_tasks", "autonomous_tasks")),
    ("worker", ("worker", "worker_loop"), ("worker_runs", "worker_events")),
    ("ejecución", ("execute", "run_task", "ejecuta"), ("runs", "worker_events")),
    ("verificación", ("verify", "verification"), ("verification_reports",)),
    ("aprendizaje", ("learn", "learning"), ("learning_queue", "learning_evidence")),
    ("Bodega", ("memory", "bodega", "store"), ("episodic_memory", "semantic_memory")),
    (
        "efecto futuro",
        ("retrieval", "inject", "apply_learning"),
        ("learning_retrieval_decisions", "neuron_education_applications"),
    ),
)

#: Eslabones que sólo producen filas cuando algo se las pide, frente a los que
#: laten solos. Distinguirlos importa porque «filas pero ninguna en 24 h»
#: significa cosas opuestas en cada caso: en un eslabón continuo es un corte; en
#: uno bajo demanda puede ser, simplemente, que nadie pidió nada.
#:
#: `plan` es el único bajo demanda hoy. Un goal nace en
#: `runner_preflight.prepare_input` → `GoalOrchestrator.accept()`, que sólo crea
#: uno cuando `CapabilityResolver` resuelve una capacidad concreta
#: (`web_research`, `test_suite`, …). Una conversación normal resuelve
#: `conversation`, devuelve `not_actionable` y **no debe** crear plan: contarlo
#: como deuda exigiría fabricar goals para limpiar el contador.
#:
#: Que el eslabón funciona está demostrado por sus propias filas: 51 goals
#: históricos de peticiones reales de la UI, 4 de ellos `completed`.
ON_DEMAND_STAGES: frozenset[str] = frozenset({"plan"})

#: En este repositorio el SQL se escribe en mayúsculas, y esa convención es lo
#: único que separa `UPDATE tabla` de un docstring que empieza por «Update».
#: Sin distinguir mayúsculas, "Update cognitive load from real sensor data"
#: producía una tabla llamada `cognitive`.
_SQL_WRITE = re.compile(
    r"\b(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM|"
    r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?)\s+[\"'`\[]?([a-z_][a-z0-9_]*)"
)
_SQL_READ = re.compile(r"\b(?:FROM|JOIN)\s+[\"'`\[]?([a-z_][a-z0-9_]*)")
_SQL_CREATE = re.compile(
    r"\bCREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+[\"'`\[]?([a-z_][a-z0-9_]*)"
)
#: Marca de que una cadena es SQL y no prosa que casualmente contiene `from`.
_SQL_VERB = re.compile(
    r"\b(?:SELECT|INSERT\s+INTO|INSERT\s+OR|UPDATE|DELETE\s+FROM|CREATE\s+TABLE)\b"
)
#: Palabras que nunca son un nombre de tabla aunque el regex las capture.
#: `ON CONFLICT DO UPDATE SET` daba una tabla `set`; `CREATE TABLE IF NOT
#: EXISTS` partido en varias líneas daba una tabla `if`.
_SQL_KEYWORDS = frozenset(
    {
        "set",
        "if",
        "not",
        "exists",
        "select",
        "from",
        "where",
        "into",
        "values",
        "table",
        "index",
        "or",
        "and",
        "replace",
        "ignore",
        "temp",
        "temporary",
        "virtual",
        "using",
        "as",
        "on",
        "conflict",
        "do",
        "nothing",
        "update",
        "delete",
        "insert",
        "distinct",
        "case",
        "when",
        "then",
        "else",
        "end",
    }
)
#: `FROM` también aparece en SQL sobre catálogos internos y en falsos positivos.
_SQL_NOISE = {"sqlite_master", "sqlite_sequence", "pragma"} | _SQL_KEYWORDS

#: Marca que ocupa el hueco de un valor interpolado en una f-string.
_DYNAMIC_MARK = "\x00DYN\x00"
#: Acceso a una tabla cuyo nombre se decide en tiempo de ejecución.
_SQL_DYNAMIC_READ = re.compile(r"\b(?:FROM|JOIN)\s+" + re.escape(_DYNAMIC_MARK))
_SQL_DYNAMIC_WRITE = re.compile(
    r"\b(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM)\s+"
    + re.escape(_DYNAMIC_MARK)
)


def _sql_literals(path: Path) -> list[tuple[str, int]]:
    """Cadenas del módulo que contienen SQL, con su línea.

    Buscar `FROM x` sobre el texto plano del fichero es lo que parece obvio y es
    justo lo que no funciona: `from pathlib import Path` encaja con el mismo
    patrón, y entonces `pathlib` acaba contada como tabla. Sólo el contenido de
    los literales de cadena puede ser SQL, así que se filtra por el AST antes de
    aplicar ningún regex.
    """
    tree = _parse_module(path)
    if tree is None:
        return []
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            text = _flatten_fstring(node)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        else:
            continue
        if not _SQL_VERB.search(text):
            continue
        found.append((text, getattr(node, "lineno", 0)))
    return found


def _flatten_fstring(node: ast.JoinedStr) -> str:
    """Aplana una f-string dejando una marca donde va el valor interpolado.

    `f"SELECT * FROM {table}"` es SQL de pleno derecho, pero el nombre de la
    tabla no está en el texto. Si se ignora, el lector desaparece del grafo; si
    se toma el texto crudo, `{table}` no encaja con nada. La marca permite
    detectar el acceso sin inventar a qué tabla apunta.
    """
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        else:
            parts.append(_DYNAMIC_MARK)
    return "".join(parts)


def open_readonly(db_path: Path | None) -> sqlite3.Connection | None:
    """Abre la base **sólo** en lectura. Nunca se escribe desde observabilidad."""
    if db_path is None or not db_path.exists():
        return None
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    connection.row_factory = sqlite3.Row
    return connection


def live_table_counts(connection: sqlite3.Connection | None) -> dict[str, int]:
    if connection is None:
        return {}
    counts: dict[str, int] = {}
    try:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
    except sqlite3.Error:
        return {}
    for name in names:
        if not name.isidentifier():
            continue
        try:
            counts[name] = int(
                connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            )
        except sqlite3.Error:
            counts[name] = -1
    return counts


def build_table_graph(
    root: Path, index: ModuleIndex | None = None, db_path: Path | None = None
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Grafo 5: tablas SQLite con sus lectores y escritores reales.

    Una tabla con filas y sin ningún lector en el código es almacenamiento que
    nadie consulta; una con escritores y cero filas es una ruta que nunca se
    ejecutó. Ambas cosas quedan explícitas en el estado del nodo.
    """
    root = root.resolve()
    index = index or build_module_index(root)
    connection = open_readonly(db_path)
    try:
        live = live_table_counts(connection)
    finally:
        if connection is not None:
            connection.close()

    declared: set[str] = set()
    readers: dict[str, set[str]] = {}
    writers: dict[str, set[str]] = {}
    evidence: dict[tuple[str, str, str], str] = {}
    #: Módulo → línea del primer acceso con nombre de tabla interpolado.
    dynamic_reads: dict[str, int] = {}
    dynamic_writes: dict[str, int] = {}
    declared_by: dict[str, set[str]] = {}

    for path in iter_python_files(root):
        relative = path.relative_to(root).as_posix()
        for statement, lineno in _sql_literals(path):
            for match in _SQL_CREATE.finditer(statement):
                table = match.group(1).lower()
                if table in _SQL_KEYWORDS:
                    continue
                declared.add(table)
                declared_by.setdefault(relative, set()).add(table)
            if _SQL_DYNAMIC_READ.search(statement):
                dynamic_reads.setdefault(relative, lineno)
            if _SQL_DYNAMIC_WRITE.search(statement):
                dynamic_writes.setdefault(relative, lineno)
            for pattern, bucket, relation in (
                (_SQL_READ, readers, "reads"),
                (_SQL_WRITE, writers, "writes"),
            ):
                for match in pattern.finditer(statement):
                    table = match.group(1).lower()
                    if table in _SQL_NOISE:
                        continue
                    bucket.setdefault(table, set()).add(relative)
                    key = (relative, table, relation)
                    if key not in evidence:
                        evidence[key] = f"{relative}:{lineno}"

    # Un módulo que consulta `f"SELECT * FROM {table}"` es lector real de las
    # tablas cuyo esquema él mismo declara. Sin esto, `qualia/store.py` —que crea
    # las cinco tablas de Qualia y las lee por un helper genérico— aparecía con
    # cero lectores, y de ahí salía la conclusión falsa de que Qualia se escribe
    # y nadie la consume. La atribución se limita a lo que el módulo declara:
    # fuera de ahí no hay forma honesta de saber a qué tabla apunta.
    for relative, lineno in sorted(dynamic_reads.items()):
        for table in declared_by.get(relative, set()):
            readers.setdefault(table, set()).add(relative)
            evidence.setdefault(
                (relative, table, "reads"), f"{relative}:{lineno} (tabla interpolada)"
            )
    for relative, lineno in sorted(dynamic_writes.items()):
        for table in declared_by.get(relative, set()):
            writers.setdefault(table, set()).add(relative)
            evidence.setdefault(
                (relative, table, "writes"), f"{relative}:{lineno} (tabla interpolada)"
            )

    known = set(live) | declared | set(readers) | set(writers)
    # Sin base viva no hay forma de distinguir una tabla real de un falso
    # positivo del regex, así que exigimos que alguien la declare o la escriba.
    if not live:
        known &= declared | set(writers)

    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    for table in sorted(known):
        table_readers = sorted(readers.get(table, set()))
        table_writers = sorted(writers.get(table, set()))
        rows = live.get(table)
        node_id = f"table:{table}"
        nodes[node_id] = GraphNode(
            node_id,
            "table",
            table,
            _table_state(table_readers, table_writers, rows),
            {
                "readers": len(table_readers),
                "writers": len(table_writers),
                "rows": rows if rows is not None else "UNKNOWN",
                "declared_in_code": table in declared,
                "live": table in live,
            },
        )
        for relation, files in (("reads", table_readers), ("writes", table_writers)):
            for relative in files:
                module_id = f"module:{relative}"
                nodes.setdefault(
                    module_id,
                    GraphNode(
                        module_id,
                        "module",
                        index.by_path.get(relative, relative),
                        "active",
                        {"path": relative},
                    ),
                )
                edges.append(
                    GraphEdge(
                        module_id,
                        node_id,
                        relation,
                        evidence.get((relative, table, relation), relative),
                    )
                )
    return sorted(nodes.values(), key=lambda n: n.node_id), edges


def _table_state(readers: list[str], writers: list[str], rows: int | None) -> NodeState:
    if not readers and not writers:
        return "disconnected"
    if rows == 0 and writers:
        return "disconnected"
    if not readers:
        return "legacy"
    if rows is None:
        return "unknown"
    return "active" if rows > 0 else "disconnected"


def literal_strings(root: Path, relative: str, name: str) -> list[str]:
    """Extrae las cadenas de un `X = Literal[...]` sin importar el módulo."""
    tree = _parse_module(root / relative)
    if tree is None:
        return []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            continue
        return [
            element.value
            for element in ast.walk(node.value)
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
    return []


def _parse_module(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
        return None


def _handler_map(root: Path, relative: str) -> dict[str, str]:
    """Encuentra el diccionario de despacho tipo→handler dentro del worker."""
    tree = _parse_module(root / relative)
    if tree is None:
        return {}
    best: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        mapping: dict[str, str] = {}
        for key, value in zip(node.keys, node.values, strict=False):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                mapping = {}
                break
            target = value
            if isinstance(target, ast.Attribute):
                mapping[key.value] = target.attr
        if len(mapping) > len(best):
            best = mapping
    return best


def build_worker_graph(
    root: Path,
    index: ModuleIndex | None = None,
    db_path: Path | None = None,
    import_edges: list[GraphEdge] | None = None,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Grafo 4: workers, tipos de tarea y su ejecución demostrada.

    Un tipo declarado sin handler no puede ejecutarse. Un tipo con handler y
    cero filas en la cola es una capacidad nominal: existe el código y nadie la
    ha pedido nunca.
    """
    root = root.resolve()
    index = index or build_module_index(root)
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    worker_modules = [
        relative
        for relative in sorted(index.by_path)
        if relative.startswith("triade/workers/")
        and not relative.endswith("__init__.py")
    ]

    # El estado de cada módulo se escribía a mano como "active" por el mero
    # hecho de que el fichero existiera, y sólo se emitían dos relaciones
    # —`contracts → tipo` y `tipo → worker_loop`—, así que ningún módulo tenía
    # nunca ni entrada ni salida: 11 de 13 salían aislados y en verde a la vez.
    # El grafo no podía detectar denervación en la propia carpeta que audita, y
    # dibujaba como desconectado el espinazo vivo del planificador
    # (`worker_loop → scheduler → mission_planner → adaptive_scheduler → task_queue`).
    #
    # Ahora las dos cosas salen de la misma evidencia: los imports reales del
    # AST y la alcanzabilidad desde un entrypoint que alguien arranca.
    # Reutilizable desde fuera igual que en `build_organ_graph`: releer el AST
    # del repositorio entero cuesta ~10 s, y el generador ya lo tiene calculado.
    if import_edges is None:
        _import_nodes, import_edges = build_import_graph(root, index)
    reachable = reachable_modules(root, index, import_edges)
    importers: dict[str, set[str]] = {}
    for edge in import_edges:
        if edge.relation != "imports":
            continue
        source = edge.source.partition(":")[2]
        target = edge.target.partition(":")[2]
        if target.startswith("triade/workers/"):
            importers.setdefault(target, set()).add(source)

    for relative in worker_modules:
        node_id = f"worker_module:{relative}"
        entrantes = importers.get(relative, set())
        vivos = sorted(entrantes & reachable)
        nodes[node_id] = GraphNode(
            node_id,
            "module",
            index.by_path[relative],
            # Importado sólo por código que jamás se ejecuta está tan denervado
            # como el que nadie nombra: los dos casos se separan en metadata.
            "active" if relative in reachable else "disconnected",
            {
                "path": relative,
                "importers": len(entrantes),
                "live_importers": vivos,
                "reachable_from_entrypoint": relative in reachable,
            },
        )

    # Aristas módulo↔módulo dentro de la carpeta, y desde los importadores de
    # fuera que están vivos. Los importadores muertos no se dibujan: pintarlos
    # sugeriría una conexión que no llega a ejecutarse nunca.
    for target, entrantes in sorted(importers.items()):
        for source in sorted(entrantes):
            if source not in reachable and source not in worker_modules:
                continue
            source_id = (
                f"worker_module:{source}"
                if source.startswith("triade/workers/")
                else f"module:{source}"
            )
            if source_id not in nodes and not source.startswith("triade/workers/"):
                nodes[source_id] = GraphNode(
                    source_id,
                    "module",
                    index.by_path.get(source, source),
                    "active",
                    {"path": source, "external_to_workers": True},
                )
            if source_id in nodes:
                edges.append(
                    GraphEdge(
                        source_id,
                        f"worker_module:{target}",
                        "imports",
                        f"{source} importa {index.by_path.get(target, target)}",
                    )
                )

    contracts = "triade/workers/contracts.py"
    loop = "triade/workers/worker_loop.py"
    declared = (
        literal_strings(root, contracts, "WorkerTaskType")
        if contracts in index.by_path
        else []
    )
    handlers = _handler_map(root, loop) if loop in index.by_path else {}

    # Con base viva, que un tipo no aparezca en la cola no es desconocimiento:
    # es la prueba de que nunca se pidió. Sin base, no se puede afirmar nada.
    db_available = db_path is not None and db_path.exists()
    executed = task_type_counts(db_path)
    recent = task_type_recency(db_path)

    for task_type in sorted(set(declared) | set(handlers)):
        node_id = f"task_type:{task_type}"
        handler = handlers.get(task_type)
        count = executed.get(task_type, 0) if db_available else None
        fresh = recent.get(task_type, False) if db_available else None
        nodes[node_id] = GraphNode(
            node_id,
            "task",
            task_type,
            _task_type_state(handler, count, fresh=fresh),
            {
                "declared": task_type in declared,
                "handler": handler or "MISSING",
                "executions": count if count is not None else "UNKNOWN",
                "recent_24h": fresh if fresh is not None else "UNKNOWN",
            },
        )
        if contracts in index.by_path and task_type in declared:
            edges.append(
                GraphEdge(
                    f"worker_module:{contracts}",
                    node_id,
                    "declares_task_type",
                    f"{contracts}:WorkerTaskType",
                )
            )
        if handler:
            edges.append(
                GraphEdge(
                    node_id,
                    f"worker_module:{loop}",
                    "handled_by",
                    f"{loop}:{handler}",
                )
            )
    return sorted(nodes.values(), key=lambda n: n.node_id), edges


def _task_type_state(
    handler: str | None, count: int | None, *, fresh: bool | None = None
) -> NodeState:
    """Estado de un tipo de tarea: sin handler, sin ejecución, o desde cuándo.

    `count` suma las dos colas, y una de ellas —`worker_tasks`— está congelada
    desde el 2026-07-29. Sin mirar la fecha, un tipo que no se ejecuta desde
    hace días sale verde igual que uno que corrió hace un minuto, y el grafo
    afirma actividad presente con evidencia caducada. `legacy` ya existe en la
    paleta para exactamente esto: «existe y se usó, sin actividad reciente».
    """
    if handler is None:
        return "disconnected"
    if count is None:
        return "unknown"
    if count <= 0:
        return "disconnected"
    if fresh is None:
        return "unknown"
    return "active" if fresh else "legacy"


#: Las dos colas de tareas. `worker_tasks` es la histórica y `autonomous_tasks`
#: la viva; se leen las dos porque el pasado también es evidencia, pero se
#: fechan por separado para no confundirlo con el presente.
TASK_TABLES = ("worker_tasks", "autonomous_tasks")


def task_type_counts(db_path: Path | None) -> dict[str, int]:
    """Ejecuciones acumuladas por tipo, sumando ambas colas.

    **Ejecuciones**, no encolados. Contaba todas las filas, así que un tipo
    encolado una vez y atascado en `pending` para siempre figuraba como
    ejecutado y desaparecía de `task_types_never_executed`. Se vio el
    2026-08-08 con `stable_consolidation_review`: se encoló por primera vez en
    la historia del sistema, seguía en `pending` con `attempt=0`, y el informe
    ya lo daba por corrido.

    Un tipo cuenta cuando dejó de estar esperando turno: `ELIGIBLE` son
    justamente los estados en los que la tarea aguarda a que alguien la tome
    (`pending`, `queued`, `recovered`, `retry_wait`, `deferred`). Todo lo demás
    —en vuelo o terminal— significa que un worker la reclamó y el handler llegó
    a decidir, aunque decidiera no actuar (`observed`, `skipped`) o fallara.
    """
    connection = open_readonly(db_path)
    if connection is None:
        return {}
    counts: dict[str, int] = {}
    espera = ",".join("?" for _ in ELIGIBLE)
    try:
        for table in TASK_TABLES:
            columnas = {
                str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
            }
            try:
                # La cola legacy no siempre trae `status`; sin esa columna no se
                # puede distinguir, y contar de más es preferible a inventar un
                # filtro que no existe.
                if "status" in columnas:
                    rows = connection.execute(
                        f"SELECT task_type, COUNT(*) FROM {table} "
                        f"WHERE status NOT IN ({espera}) GROUP BY task_type",
                        tuple(sorted(ELIGIBLE)),
                    )
                else:
                    rows = connection.execute(
                        f"SELECT task_type, COUNT(*) FROM {table} GROUP BY task_type"
                    )
            except sqlite3.Error:
                continue
            for task_type, total in rows:
                if task_type is None:
                    continue
                counts[str(task_type)] = counts.get(str(task_type), 0) + int(total)
    finally:
        connection.close()
    return counts


def task_type_recency(db_path: Path | None, *, hours: int = 24) -> dict[str, bool]:
    """¿Se ejecutó este tipo en las últimas `hours`?

    El corte se calcula con `strftime` en formato con `T`, igual que
    `recent_activity()`: las tablas guardan ISO-8601 con `T` y `datetime('now')`
    usa espacio, así que comparar los dos formatos ensancha la ventana en
    silencio.
    """
    connection = open_readonly(db_path)
    if connection is None:
        return {}
    fresh: dict[str, bool] = {}
    try:
        for table in TASK_TABLES:
            try:
                rows = connection.execute(
                    f"SELECT task_type, COUNT(*) FROM {table} "
                    "WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?) "
                    "GROUP BY task_type",
                    (f"-{int(hours)} hours",),
                ).fetchall()
            except sqlite3.Error:
                continue
            for task_type, total in rows:
                if task_type is None:
                    continue
                key = str(task_type)
                fresh[key] = fresh.get(key, False) or int(total) > 0
    finally:
        connection.close()
    return fresh


def build_organ_graph(
    root: Path,
    index: ModuleIndex | None = None,
    db_path: Path | None = None,
    import_edges: list[GraphEdge] | None = None,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Grafo 6: órganos de Tríade y sus conexiones demostradas por imports."""
    root = root.resolve()
    index = index or build_module_index(root)
    if import_edges is None:
        from .code_graph import build_import_graph

        _, import_edges = build_import_graph(root, index)

    owner: dict[str, str] = {}
    members: dict[str, list[str]] = {}
    for organ, prefixes in ORGAN_PATHS.items():
        for relative in sorted(index.by_path):
            if any(relative.startswith(prefix) for prefix in prefixes):
                owner.setdefault(relative, organ)
                members.setdefault(organ, []).append(relative)

    _table_nodes, table_edges = build_table_graph(root, index, db_path)
    tables_by_module: dict[str, set[str]] = {}
    for edge in table_edges:
        relative = edge.source.partition(":")[2]
        tables_by_module.setdefault(relative, set()).add(edge.target.partition(":")[2])

    nodes: dict[str, GraphNode] = {}
    for organ, prefixes in ORGAN_PATHS.items():
        present = [p for p in prefixes if (root / p).is_dir()]
        organ_members = members.get(organ, [])
        organ_tables: set[str] = set()
        for relative in organ_members:
            organ_tables |= tables_by_module.get(relative, set())
        node_id = f"organ:{organ}"
        nodes[node_id] = GraphNode(
            node_id,
            "module",
            organ,
            "active" if organ_members else "disconnected",
            {
                "paths": present,
                "declared_paths": list(prefixes),
                "modules": len(organ_members),
                "tables": sorted(organ_tables),
            },
        )

    counted: dict[tuple[str, str], int] = {}
    for edge in import_edges:
        if edge.relation != "imports":
            continue
        source = owner.get(edge.source.partition(":")[2])
        target = owner.get(edge.target.partition(":")[2])
        if source is None or target is None or source == target:
            continue
        counted[(source, target)] = counted.get((source, target), 0) + 1

    edges = [
        GraphEdge(
            f"organ:{source}",
            f"organ:{target}",
            "connects_to",
            f"{total} imports internos",
            {"imports": total},
        )
        for (source, target), total in sorted(counted.items())
    ]
    return sorted(nodes.values(), key=lambda n: n.node_id), edges


def build_vital_chain_graph(
    root: Path, index: ModuleIndex | None = None, db_path: Path | None = None
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Grafo 7: continuidad vital, eslabón a eslabón, con evidencia por etapa.

    `VERIFIED` exige código **y** filas recientes. Código sin filas es
    `DISCONNECTED_PULSE`; filas sin código que las escriba hoy es
    `STALE_EVIDENCE`. Sin base viva todo eslabón queda en `NEEDS_EVIDENCE`.

    Eso vale para los **nodos**. Las **aristas** no se verifican igual y por eso
    lo dicen: el orden de la cadena sale de `VITAL_CHAIN`, una constante de este
    repositorio, y nada comprueba fila a fila que una etapa alimente a la
    siguiente. Se marca `handoff_verified` sólo cuando ambos extremos tienen
    actividad reciente, que sigue sin demostrar el traspaso —demuestra que los
    dos extremos están vivos—, y se distingue en la propia evidencia.

    La arista citaba antes como evidencia un documento de instrucciones de una
    herramienta externa de desarrollo. Era la fuente equivocada: una herramienta
    externa no es parte de Tríade y no puede ser autoridad dentro de su grafo, y
    la documentación es la última prioridad de evidencia —válida sólo cuando
    coincide con el código y los datos—. Ese documento ya no existe en el
    repositorio; la cadena la declara `VITAL_CHAIN` y nada más. Una arista
    dibujada siempre, con o sin datos, es justo el «pinta verde por existir» que
    este grafo debería detectar.
    """
    root = root.resolve()
    index = index or build_module_index(root)
    connection = open_readonly(db_path)
    try:
        live = live_table_counts(connection)
        recent = recent_activity(
            connection, [t for _, _, ts in VITAL_CHAIN for t in ts]
        )
    finally:
        if connection is not None:
            connection.close()

    symbol_hits = _symbol_hits(root, index, VITAL_CHAIN)

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    previous: tuple[str, NodeState] | None = None
    for stage, anchors, tables in VITAL_CHAIN:
        node_id = f"stage:{stage}"
        hits = symbol_hits.get(stage, [])
        present = [t for t in tables if t in live]
        rows = sum(live.get(t, 0) for t in present)
        fresh = any(recent.get(t) for t in present)
        state = _stage_state(bool(hits), bool(live), rows, fresh)
        nodes.append(
            GraphNode(
                node_id,
                "function",
                stage,
                state,
                {
                    "anchors": list(anchors),
                    "code_evidence": hits[:5],
                    "code_matches": len(hits),
                    "tables": list(tables),
                    "tables_present": present,
                    "rows": rows if live else "UNKNOWN",
                    "recent_24h": fresh if live else "UNKNOWN",
                },
            )
        )
        if previous is not None:
            prev_stage, prev_state = previous
            ambos_vivos = prev_state == "active" and state == "active"
            edges.append(
                GraphEdge(
                    f"stage:{prev_stage}",
                    node_id,
                    "feeds",
                    (
                        "orden en VITAL_CHAIN; ambos eslabones con actividad "
                        "reciente (el traspaso no se sigue fila a fila)"
                        if ambos_vivos
                        else "orden en VITAL_CHAIN; traspaso NO verificado por datos"
                    ),
                    {
                        "order_source": "VITAL_CHAIN",
                        "handoff_verified": ambos_vivos,
                        "source_state": prev_state,
                        "target_state": state,
                    },
                )
            )
        previous = (stage, state)
    return nodes, edges


def _stage_state(has_code: bool, has_db: bool, rows: int, fresh: bool) -> NodeState:
    if not has_code:
        return "disconnected"
    if not has_db:
        return "unknown"
    if rows == 0:
        return "disconnected"
    return "active" if fresh else "legacy"


def _symbol_hits(
    root: Path,
    index: ModuleIndex,
    chain: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...],
) -> dict[str, list[str]]:
    """Busca cada ancla entre los símbolos definidos, no en texto libre."""
    hits: dict[str, list[str]] = {stage: [] for stage, _, _ in chain}
    for relative in sorted(index.by_path):
        tree = _parse_module(root / relative)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            lowered = node.name.lower()
            for stage, anchors, _ in chain:
                if any(anchor.lower() in lowered for anchor in anchors):
                    hits[stage].append(f"{relative}:{node.name}:{node.lineno}")
    return {stage: sorted(found) for stage, found in hits.items()}


def recent_activity(
    connection: sqlite3.Connection | None, tables: list[str]
) -> dict[str, bool]:
    """¿Escribió alguien en las últimas 24 h?

    Las tablas guardan ISO-8601 con `T`, y `datetime('now')` usa espacio: la
    comparación textual entre ambos formatos ensancha la ventana en silencio.
    Por eso el corte se calcula con `strftime` en el mismo formato con `T`.
    """
    if connection is None:
        return {}
    fresh: dict[str, bool] = {}
    for table in sorted(set(tables)):
        if not table.isidentifier():
            continue
        try:
            columns = {
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            }
        except sqlite3.Error:
            continue
        column = next(
            (
                c
                for c in ("created_at", "updated_at", "started_at", "ts")
                if c in columns
            ),
            None,
        )
        if column is None:
            continue
        try:
            row = connection.execute(
                f"SELECT COUNT(*) FROM {table} "  # identificador validado con isidentifier()
                f"WHERE {column} >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-1 day')"
            ).fetchone()
        except sqlite3.Error:
            continue
        fresh[table] = bool(row and row[0])
    return fresh


def iter_all_paths(root: Path) -> Iterator[Path]:
    """Todo el árbol, incluido lo oculto, salvo caché y secretos."""
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(
            part in {"__pycache__", ".git", "node_modules"} for part in relative.parts
        ):
            continue
        yield path

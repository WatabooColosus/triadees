"""Las acciones reales del sistema, según ocurren, ancladas a nodos del grafo.

Un grafo que sólo informa de totales dice cómo está el sistema. Este módulo dice
qué está *haciendo*: cada tarea que termina, cada transición de cola, cada
neurona que se activa, cada run y cada llamada a modelo, en el momento en que
queda escrita.

Dos propiedades que no son negociables:

- **Completo.** Se lee por cursor sobre claves monótonas, no por ventana de
  tiempo. Entre dos lecturas no se pierde nada aunque el lector se pare: el
  cursor recuerda por dónde iba.
- **Verificable.** Cada evento lleva la tabla y el identificador de la fila que
  lo respalda, así que siempre se puede ir a mirarla.

Todo se lee en `mode=ro`. Este módulo no escribe nunca.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .runtime_graph import open_readonly

#: Cuántos eventos como mucho por lectura. Un arranque en frío sobre una base
#: con 31 000 eventos no puede volcarlos todos en el primer pulso.
DEFAULT_LIMIT = 40


@dataclass(frozen=True, slots=True)
class EventSource:
    """De dónde sale un evento y a qué nodo del grafo afecta."""

    table: str
    key: str
    timestamp: str
    graph: str
    columns: tuple[str, ...]


#: El orden importa: se emite del más específico al más general, de modo que un
#: pulso corto muestre antes el trabajo que el ruido de fondo.
SOURCES: tuple[EventSource, ...] = (
    EventSource(
        "worker_events",
        "id",
        "created_at",
        "workers",
        ("task_type", "event_type", "status", "run_ref"),
    ),
    EventSource(
        "autonomous_task_transitions",
        "transition_id",
        "created_at",
        "vital_chain",
        ("task_id", "from_status", "to_status", "reason"),
    ),
    EventSource(
        "neuron_activity",
        "id",
        "created_at",
        "neural",
        ("neuron_id", "name", "domain", "status", "activation_type"),
    ),
    EventSource("runs", "id", "created_at", "neural", ("run_id", "source", "status")),
    EventSource(
        "model_events",
        "id",
        "created_at",
        "organs",
        ("run_id", "role", "model_name", "ok"),
    ),
)


@dataclass
class FeedCursor:
    """Por dónde iba la lectura de cada tabla."""

    positions: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, int]:
        return dict(self.positions)

    @classmethod
    def from_dict(cls, raw: dict[str, int] | None) -> FeedCursor:
        return cls(positions=dict(raw or {}))


def latest_cursor(db_path: Path | None) -> FeedCursor:
    """Cursor situado en el presente: sólo interesa lo que pase a partir de ahora.

    Sin esto, el primer pulso de cada cliente volcaría el historial entero como
    si acabara de ocurrir, que es exactamente la clase de mentira que estos
    grafos existen para evitar.
    """
    cursor = FeedCursor()
    connection = open_readonly(db_path)
    if connection is None:
        return cursor
    try:
        for source in SOURCES:
            try:
                row = connection.execute(
                    f"SELECT MAX({source.key}) FROM {source.table}"  # identificador de tabla fijo en SOURCES
                ).fetchone()
            except sqlite3.Error:
                continue
            cursor.positions[source.table] = int(row[0] or 0) if row else 0
    finally:
        connection.close()
    return cursor


def read_new_events(
    db_path: Path | None,
    cursor: FeedCursor,
    *,
    limit: int = DEFAULT_LIMIT,
) -> tuple[list[dict[str, Any]], FeedCursor]:
    """Devuelve lo ocurrido desde el cursor, y el cursor avanzado."""
    connection = open_readonly(db_path)
    if connection is None:
        return [], cursor
    connection.row_factory = sqlite3.Row
    events: list[dict[str, Any]] = []
    advanced = FeedCursor(positions=dict(cursor.positions))
    try:
        for source in SOURCES:
            since = cursor.positions.get(source.table)
            if since is None:
                # Tabla nueva para este cursor: se sitúa sin emitir historial.
                try:
                    row = connection.execute(
                        f"SELECT MAX({source.key}) FROM {source.table}"  # identificador de tabla fijo en SOURCES
                    ).fetchone()
                    advanced.positions[source.table] = int(row[0] or 0) if row else 0
                except sqlite3.Error:
                    pass
                continue
            try:
                available = {
                    r[1]
                    for r in connection.execute(f"PRAGMA table_info({source.table})")
                }
                selected = [c for c in source.columns if c in available]
                fields = ", ".join([source.key, *selected])
                if source.timestamp in available:
                    fields += f", {source.timestamp}"
                rows = connection.execute(
                    f"SELECT {fields} FROM {source.table} "  # identificador de tabla fijo en SOURCES
                    f"WHERE {source.key} > ? ORDER BY {source.key} ASC LIMIT ?",
                    (since, limit),
                ).fetchall()
            except sqlite3.Error:
                continue
            for row in rows:
                identifier = int(row[source.key])
                advanced.positions[source.table] = max(
                    advanced.positions.get(source.table, 0), identifier
                )
                events.append(_describe(source, row, identifier))
    finally:
        connection.close()
    events.sort(key=lambda e: e.get("at") or "")
    return events, advanced


def read_recent_events(
    db_path: Path | None,
    *,
    limit: int = DEFAULT_LIMIT,
    run_id: str | None = None,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    """Lee historia reciente verificable, separada del cursor SSE vivo.

    El stream conserva su contrato de no inventar historia al conectar. Esta
    lectura explícita existe para la timeline y sólo devuelve filas persistidas;
    los filtros se aplican sobre las columnas reales de cada fuente.
    """
    connection = open_readonly(db_path)
    if connection is None:
        return []
    connection.row_factory = sqlite3.Row
    events: list[dict[str, Any]] = []
    try:
        for source in SOURCES:
            try:
                available = {
                    str(row[1])
                    for row in connection.execute(f"PRAGMA table_info({source.table})")
                }
                selected = [column for column in source.columns if column in available]
                fields = ", ".join([source.key, *selected])
                if source.timestamp in available:
                    fields += f", {source.timestamp}"
                clauses: list[str] = []
                params: list[Any] = []
                if run_id and "run_id" in available:
                    clauses.append("run_id = ?")
                    params.append(run_id)
                elif run_id and "run_ref" in available:
                    clauses.append("run_ref = ?")
                    params.append(run_id)
                if task_id and "task_id" in available:
                    clauses.append("CAST(task_id AS TEXT) = ?")
                    params.append(task_id)
                where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
                rows = connection.execute(
                    f"SELECT {fields} FROM {source.table}{where} "
                    f"ORDER BY {source.key} DESC LIMIT ?",
                    (*params, max(1, limit)),
                ).fetchall()
            except sqlite3.Error:
                continue
            events.extend(_describe(source, row, int(row[source.key])) for row in rows)
    finally:
        connection.close()
    events.sort(key=lambda event: event.get("at") or "", reverse=True)
    return events[: max(1, limit)]


def _describe(source: EventSource, row: sqlite3.Row, identifier: int) -> dict[str, Any]:
    keys = set(row.keys())
    data = {c: row[c] for c in source.columns if c in keys}
    return {
        "source": source.table,
        "row_id": identifier,
        "at": row[source.timestamp] if source.timestamp in keys else None,
        "graph": source.graph,
        "node_id": _node_for(source.table, data),
        "action": _action(source.table, data),
        "status": _status(data),
        # La evidencia es la fila exacta: se puede ir a verla.
        "evidence": f"sqlite:{source.table}.{source.key}={identifier}",
        "data": data,
        "simulated": False,
    }


def _node_for(table: str, data: dict[str, Any]) -> str | None:
    """Nodo del grafo al que pertenece la acción, si se puede determinar."""
    if table == "worker_events" and data.get("task_type"):
        return f"task_type:{data['task_type']}"
    if table == "neuron_activity" and data.get("neuron_id") is not None:
        return f"neuron:{data['neuron_id']}"
    if table == "runs" and data.get("run_id"):
        return f"run:{data['run_id']}"
    if table == "autonomous_task_transitions":
        return "stage:cola"
    if table == "model_events":
        return "organ:Ollama Blood"
    return None


def _action(table: str, data: dict[str, Any]) -> str:
    if table == "worker_events":
        return f"{data.get('task_type', '?')} · {data.get('event_type', '?')}"
    if table == "autonomous_task_transitions":
        return f"cola: {data.get('from_status', '?')} → {data.get('to_status', '?')}"
    if table == "neuron_activity":
        return f"neurona {data.get('name') or data.get('neuron_id')} activada"
    if table == "runs":
        return f"run {data.get('run_id')} · {data.get('source', '?')}"
    if table == "model_events":
        return f"modelo {data.get('model_name', '?')} · {data.get('role', '?')}"
    return table


#: Un fallo tiene que saltar a la vista. Si casi todo cae en `unknown`, el
#: registro se vuelve gris y un error real pasa desapercibido: los servicios
#: escriben `info` y eso dejaba el 90 % de las líneas sin estado.
_FAILED_STATUSES = frozenset(
    {"failed", "error", "dead_letter", "timeout", "lease_lost", "cancelled", "blocked"}
)
_ACTIVE_STATUSES = frozenset(
    {
        "ok",
        "info",
        "completed",
        "observed",
        "running",
        "claimed",
        "pending",
        "started",
        "success",
    }
)
#: Estados que existen pero no afirman nada: se muestran como tales.
_AMBIGUOUS_STATUSES = frozenset({"completion_uncertain", "skipped", "dry_run"})


def _status(data: dict[str, Any]) -> str:
    """Estado normalizado, con el mismo vocabulario que los nodos del grafo."""
    raw = data.get("status")
    if raw is None and "ok" in data:
        raw = "ok" if data["ok"] else "failed"
    if raw is None:
        raw = data.get("to_status")
    value = str(raw or "").lower()
    if value in _FAILED_STATUSES:
        return "failed"
    if value in _ACTIVE_STATUSES:
        return "active"
    if value in _AMBIGUOUS_STATUSES:
        return "unknown"
    return "unknown"

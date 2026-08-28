"""El grafo de workers no puede afirmar actividad presente con datos caducados.

`task_type_counts()` suma `worker_tasks` y `autonomous_tasks`. La primera está
congelada desde el 2026-07-29, y mientras el estado se decidiera sólo por
`count > 0`, dos tipos que no se ejecutan desde hace días —`experimental_neuron_activity`
con 2 499 filas y `memory_consolidation_review` con 208— salían en verde
exactamente igual que `pulse_check`, que corre cada minuto.

Una tarea periódica sin latido sigue siendo `legacy`. Una tarea bajo demanda con
productor y consumidor verificados queda `ready`: conectada, pero sin fingir una
ejecución que no ocurrió.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.observability.code_graph import build_module_index
from triade.observability.runtime_graph import (
    _task_type_state,
    build_worker_graph,
    recent_activity,
    task_type_counts,
    task_type_recency,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _db_con_dos_colas(tmp_path: Path) -> Path:
    """Reproduce la forma real: una cola congelada y otra viva."""
    db = tmp_path / "triade.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE worker_tasks (
            id INTEGER PRIMARY KEY, task_type TEXT, created_at TEXT);
        CREATE TABLE autonomous_tasks (
            id INTEGER PRIMARY KEY, task_type TEXT, created_at TEXT);
        """
    )
    # Congelada: muchas filas, todas viejas.
    conn.executemany(
        "INSERT INTO worker_tasks (task_type, created_at) VALUES (?, ?)",
        [("experimental_neuron_activity", "2026-07-29T04:12:31.585223+00:00")] * 25,
    )
    # Viva: se escribe ahora mismo, en el formato ISO con `T` de la base real.
    conn.execute(
        "INSERT INTO autonomous_tasks (task_type, created_at) VALUES "
        "('pulse_check', strftime('%Y-%m-%dT%H:%M:%S', 'now'))"
    )
    conn.commit()
    conn.close()
    return db


def test_una_cola_congelada_no_cuenta_como_actividad_reciente(tmp_path: Path) -> None:
    db = _db_con_dos_colas(tmp_path)

    counts = task_type_counts(db)
    fresh = task_type_recency(db)

    # El pasado se sigue contando: es evidencia de que el tipo existió.
    assert counts["experimental_neuron_activity"] == 25
    assert counts["pulse_check"] == 1
    # Pero no se confunde con el presente.
    assert fresh.get("experimental_neuron_activity", False) is False
    assert fresh["pulse_check"] is True


def test_recency_accepts_current_timestamp_with_space(tmp_path: Path) -> None:
    """Los dos formatos reales de SQLite pertenecen a la misma línea temporal."""
    db = tmp_path / "mixed.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE events(created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("INSERT INTO events DEFAULT VALUES")
    conn.commit()

    fresh = recent_activity(conn, ["events"])
    conn.close()

    assert fresh["events"] is True


def test_el_grafo_separa_bajo_demanda_preparado_de_actividad_real(
    tmp_path: Path,
) -> None:
    db = _db_con_dos_colas(tmp_path)
    nodes, _edges = build_worker_graph(REPO_ROOT, build_module_index(REPO_ROOT), db)
    por_tipo = {n.label: n for n in nodes if n.node_id.startswith("task_type:")}

    congelado = por_tipo["experimental_neuron_activity"]
    assert congelado.state == "ready"
    assert congelado.metadata["executions"] == 25
    assert congelado.metadata["recent_24h"] is False
    assert congelado.metadata["activation_classification"] == "ON_DEMAND"

    vivo = por_tipo["pulse_check"]
    assert vivo.state == "active"
    assert vivo.metadata["recent_24h"] is True


def test_nunca_ejecutado_sigue_siendo_disconnected(tmp_path: Path) -> None:
    db = _db_con_dos_colas(tmp_path)
    nodes, _edges = build_worker_graph(REPO_ROOT, build_module_index(REPO_ROOT), db)
    por_tipo = {n.label: n for n in nodes if n.node_id.startswith("task_type:")}

    nunca = por_tipo["bodega_global_review"]
    assert nunca.state == "disconnected"
    assert nunca.metadata["executions"] == 0


def test_sin_base_el_estado_es_unknown_no_inventado() -> None:
    """Sin evidencia no se afirma nada: es la regla del grafo entero."""
    assert _task_type_state("handler", None) == "unknown"
    assert _task_type_state(None, 10, fresh=True) == "disconnected"
    # Hay ejecuciones pero no se sabe si son recientes: tampoco se pinta verde.
    assert _task_type_state("handler", 10, fresh=None) == "unknown"
    assert _task_type_state("handler", 10, fresh=False) == "legacy"
    assert _task_type_state("handler", 10, fresh=True) == "active"
    assert _task_type_state("handler", 0, fresh=False, ready_when_idle=True) == "ready"

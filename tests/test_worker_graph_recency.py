"""El grafo de workers no puede afirmar actividad presente con datos caducados.

`task_type_counts()` suma `worker_tasks` y `autonomous_tasks`. La primera está
congelada desde el 2026-07-29, y mientras el estado se decidiera sólo por
`count > 0`, dos tipos que no se ejecutan desde hace días —`experimental_neuron_activity`
con 2 499 filas y `memory_consolidation_review` con 208— salían en verde
exactamente igual que `pulse_check`, que corre cada minuto.

`legacy` ya existía en la paleta con el significado correcto: «existe y se usó,
sin actividad reciente».
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.observability.code_graph import build_module_index
from triade.observability.runtime_graph import (
    _task_type_state,
    build_worker_graph,
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


def test_el_grafo_pinta_legacy_lo_que_se_uso_y_ya_no(tmp_path: Path) -> None:
    db = _db_con_dos_colas(tmp_path)
    nodes, _edges = build_worker_graph(REPO_ROOT, build_module_index(REPO_ROOT), db)
    por_tipo = {n.label: n for n in nodes if n.node_id.startswith("task_type:")}

    congelado = por_tipo["experimental_neuron_activity"]
    assert congelado.state == "legacy"
    assert congelado.metadata["executions"] == 25
    assert congelado.metadata["recent_24h"] is False

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

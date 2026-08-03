"""La observabilidad tiene que servir a dos consumidores reales.

Fuera: el frontend, que necesita ver qué pasa mientras pasa. Dentro: la propia
Tríade, que necesita leer su estructura para decidir en qué trabajar. Un grafo
que sólo mira un auditor externo es otra tabla que se escribe y nadie lee.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps import internal_graphs_live
from apps.single_port_app import app
from triade.observability.event_feed import latest_cursor, read_new_events
from triade.observability.introspection import (
    build_debt_report,
    summarise_for_humans,
    unexecuted_task_types,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "triade.db"
    connection = sqlite3.connect(db)
    connection.executescript(
        """
        CREATE TABLE runs (run_id TEXT PRIMARY KEY, status TEXT, created_at TEXT);
        CREATE TABLE autonomous_tasks (id INTEGER PRIMARY KEY, run_id TEXT, status TEXT, task_type TEXT);
        CREATE TABLE worker_tasks (id INTEGER PRIMARY KEY, task_type TEXT, created_at TEXT);
        CREATE TABLE worker_events (id INTEGER PRIMARY KEY AUTOINCREMENT, run_ref TEXT,
            task_id TEXT, task_type TEXT, event_type TEXT, status TEXT, message TEXT,
            payload_json TEXT, created_at TEXT);
        INSERT INTO runs VALUES ('real-run', 'running', '2026-08-02T23:00:00Z');
        INSERT INTO autonomous_tasks VALUES (1, 'real-run', 'running', 'pulse_check');
        """
    )
    connection.commit()
    connection.close()
    return db


# --- Lectura externa: el frontend ---------------------------------------------


def test_live_snapshot_reads_real_sources_without_simulation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIADE_DB_PATH", str(_db(tmp_path)))
    internal_graphs_live._cache.clear()

    snapshot = internal_graphs_live.build_live_snapshot(file_limit=50, neural_limit=50)

    assert snapshot["source"]["simulated"] is False
    assert snapshot["database"]["integrity"] == "ok"
    assert snapshot["resources"]["pid"] > 0
    assert any(
        node["node_id"] == "run:real-run" for node in snapshot["neural"]["nodes"]
    )


def test_pulse_carries_live_signals_not_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El pulso debe ser barato: relee SQLite, nunca el AST del repositorio."""
    monkeypatch.setenv("TRIADE_DB_PATH", str(_db(tmp_path)))
    internal_graphs_live._cache.clear()

    pulse, _ = internal_graphs_live.build_pulse()

    assert pulse["simulated"] is False
    assert pulse["legend"], "el color viaja con el pulso para que la UI no lo invente"
    signals = pulse["signals"]
    assert "LIFE_PULSE" in signals["stages"]
    # Los tipos declarados sin una sola ejecución son justo lo que hay que ver.
    assert signals["task_types"]["pulse_check"]["executions"] == 1
    assert signals["task_types"]["goal_lora_train"]["executions"] == 0
    assert signals["task_types"]["goal_lora_train"]["state"] == "disconnected"


def test_graph_and_node_routes_expose_color_and_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # La app crea su propio esquema al arrancar: se le da una ruta virgen para
    # no chocar con `schemas.sql`, que define `runs` con más columnas.
    monkeypatch.setenv("TRIADE_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("TRIADE_DISABLE_BACKGROUND", "1")
    internal_graphs_live._cache.clear()

    with TestClient(app) as client:
        ui = client.get("/internal-graphs")
        catalog = client.get("/api/internal-graphs/catalog")
        graph = client.get("/api/internal-graphs/graph/vital_chain")
        missing = client.get("/api/internal-graphs/graph/no-existe")
        detail = client.get(
            "/api/internal-graphs/node/vital_chain", params={"node_id": "stage:Bodega"}
        )

    assert ui.status_code == 200
    assert 'EventSource("/api/internal-graphs/stream")' in ui.text
    assert catalog.json()["graphs"][0] == "physical"
    assert missing.status_code == 404

    payload = graph.json()
    assert payload["nodes"], "la cadena vital nunca está vacía"
    for node in payload["nodes"]:
        assert node["color"].startswith("#"), "cada nodo llega con su color resuelto"

    body = detail.json()
    assert body["node"]["label"] == "Bodega"
    assert body["degree"]["in"] + body["degree"]["out"] > 0


# --- Lectura interna: la propia Tríade ----------------------------------------


def test_debt_report_is_measured_from_graphs_and_live_rows(tmp_path: Path) -> None:
    cache = tmp_path / "graphs"
    report = build_debt_report(REPO_ROOT, _db(tmp_path), cache, max_age_seconds=0)

    assert report["status"] == "measured"
    assert report["simulated"] is False
    assert report["formula"], "un recuento sin fórmula no es medible"
    items = report["items"]
    for name in (
        "task_types_never_executed",
        "tables_written_never_read",
        "tables_with_writer_and_no_rows",
        "modules_without_importer",
        "entrypoints_without_launcher",
        "vital_chain_gaps",
    ):
        assert name in items, name
        assert items[name]["evidence"], f"{name} sin evidencia"
    assert report["debt_items_total"] == sum(e["count"] for e in items.values())
    # `pulse_check` corrió una vez en esta base; `goal_lora_train` ninguna.
    idle = unexecuted_task_types(report)
    assert "goal_lora_train" in idle
    assert "pulse_check" not in idle


def test_debt_report_reuses_fresh_graphs_instead_of_rescanning(tmp_path: Path) -> None:
    """Reconstruir el AST en cada ciclo del worker costaría más que el trabajo."""
    cache = tmp_path / "graphs"
    db = _db(tmp_path)
    build_debt_report(REPO_ROOT, db, cache, max_age_seconds=0)
    stamp = (cache / "index.json").stat().st_mtime

    build_debt_report(REPO_ROOT, db, cache, max_age_seconds=3600)

    assert (cache / "index.json").stat().st_mtime == stamp, "no debió regenerar"


def test_debt_report_says_unknown_instead_of_inventing(tmp_path: Path) -> None:
    report = build_debt_report(REPO_ROOT, None, tmp_path / "vacio", allow_build=False)
    assert report["status"] == "unknown"
    assert report["items"] == {}
    assert "no medible" in summarise_for_humans(report).lower()


def test_debt_summary_is_readable_and_carries_numbers(tmp_path: Path) -> None:
    cache = tmp_path / "graphs"
    report = build_debt_report(REPO_ROOT, _db(tmp_path), cache, max_age_seconds=0)
    summary = summarise_for_humans(report)
    assert "deuda estructural" in summary.lower()
    assert any(char.isdigit() for char in summary), "un resumen sin cifras no mide nada"
    # Lo que va a Qualia debe poder serializarse sin perder los recuentos.
    counts = {name: entry["count"] for name, entry in report["items"].items()}
    assert json.loads(json.dumps(counts, sort_keys=True)) == counts


# --- Las acciones reales, según ocurren --------------------------------------


def test_feed_starts_in_the_present_not_in_the_history(tmp_path: Path) -> None:
    """Volcar el historial en el primer pulso sería presentar lo viejo como nuevo."""
    db = _db(tmp_path)
    cursor = latest_cursor(db)
    events, _ = read_new_events(db, cursor)
    assert events == []


def test_feed_is_complete_and_verifiable(tmp_path: Path) -> None:
    """Nada se salta entre lecturas, y cada acción apunta a su fila."""
    db = _db(tmp_path)
    cursor = latest_cursor(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS worker_events ("
            "id INTEGER PRIMARY KEY, run_ref TEXT, task_id TEXT, task_type TEXT,"
            " event_type TEXT, status TEXT, message TEXT, payload_json TEXT,"
            " created_at TEXT)"
        )
        for i, (task, status) in enumerate(
            [("pulse_check", "ok"), ("goal_lora_train", "failed")], start=1
        ):
            conn.execute(
                "INSERT INTO worker_events (task_type, event_type, status, created_at)"
                " VALUES (?, 'task_completed', ?, ?)",
                (task, status, f"2026-08-03T03:00:0{i}"),
            )

    events, advanced = read_new_events(db, cursor)

    assert len(events) == 2
    assert [e["action"] for e in events] == [
        "pulse_check · task_completed",
        "goal_lora_train · task_completed",
    ]
    assert [e["status"] for e in events] == ["active", "failed"]
    assert events[0]["node_id"] == "task_type:pulse_check"
    for event in events:
        assert event["evidence"].startswith("sqlite:worker_events.id=")
        assert event["simulated"] is False

    # El cursor avanzó: una segunda lectura no repite lo ya entregado.
    again, _ = read_new_events(db, advanced)
    assert again == []


def test_pulse_carries_actions_and_advances_its_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIADE_DB_PATH", str(_db(tmp_path)))
    internal_graphs_live._cache.clear()

    first, cursor = internal_graphs_live.build_pulse()
    assert first["events"] == []
    assert first["schema_version"] == 4

    with sqlite3.connect(tmp_path / "triade.db") as conn:
        conn.execute(
            "INSERT INTO worker_events (task_type, event_type, status, created_at)"
            " VALUES ('pulse_check', 'task_completed', 'ok', '2026-08-03T03:00:00')"
        )

    second, advanced = internal_graphs_live.build_pulse(cursor)

    assert [e["action"] for e in second["events"]] == ["pulse_check · task_completed"]
    assert second["cursor"]["worker_events"] == advanced.positions["worker_events"]
    # Un tercer pulso no repite la acción ya entregada.
    third, _ = internal_graphs_live.build_pulse(advanced)
    assert third["events"] == []


def test_failures_stand_out_from_routine_activity(tmp_path: Path) -> None:
    """Si todo cae en `unknown`, un fallo real pasa desapercibido."""
    db = _db(tmp_path)
    cursor = latest_cursor(db)
    with sqlite3.connect(db) as conn:
        for i, (task, status) in enumerate(
            [
                ("internal_runtime", "info"),
                ("goal_lora_train", "dead_letter"),
                ("pulse_check", "completion_uncertain"),
            ],
            start=1,
        ):
            conn.execute(
                "INSERT INTO worker_events (task_type, event_type, status, created_at)"
                " VALUES (?, 'task_completed', ?, ?)",
                (task, status, f"2026-08-03T04:00:0{i}"),
            )

    events, _ = read_new_events(db, cursor)

    assert [e["status"] for e in events] == ["active", "failed", "unknown"]

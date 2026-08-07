"""La observabilidad tiene que servir a dos consumidores reales.

Fuera: el frontend, que necesita ver qué pasa mientras pasa. Dentro: la propia
Tríade, que necesita leer su estructura para decidir en qué trabajar. Un grafo
que sólo mira un auditor externo es otra tabla que se escribe y nadie lee.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps import internal_graphs_live
from apps.single_port_app import app
from triade.observability.event_feed import latest_cursor, read_new_events
from triade.observability.introspection import (
    _vital_chain_gaps,
    build_debt_report,
    summarise_for_humans,
    unexecuted_task_types,
)
from triade.observability.refresh import GraphRefresher

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


def _chain_db(tmp_path: Path, *, plan_rows: int, plan_recent: bool) -> Path:
    """Base mínima con el eslabón `plan` y un eslabón continuo (`worker`)."""
    db = tmp_path / "cadena.db"
    old = "2026-08-01T06:49:28+00:00"
    connection = sqlite3.connect(db)
    connection.executescript(
        """
        CREATE TABLE planning_graph (goal_id TEXT PRIMARY KEY, created_at TEXT);
        CREATE TABLE worker_runs (id INTEGER PRIMARY KEY, created_at TEXT);
        """
    )
    stamp = datetime.now(UTC).isoformat() if plan_recent else old
    for i in range(plan_rows):
        connection.execute("INSERT INTO planning_graph VALUES (?, ?)", (f"g{i}", stamp))
    # El eslabón continuo tiene filas, todas viejas: eso sí debe salir como corte.
    connection.execute("INSERT INTO worker_runs VALUES (1, ?)", (old,))
    connection.commit()
    connection.close()
    return db


def test_idle_on_demand_stage_is_not_a_gap(tmp_path: Path) -> None:
    """`plan` sin filas recientes no es un corte: nadie pidió una capacidad.

    Un goal sólo nace cuando `CapabilityResolver` resuelve una capacidad
    concreta; una conversación normal resuelve `conversation` y devuelve
    `not_actionable`. Contarlo como deuda obligaría a fabricar goals para
    limpiar el contador. El eslabón continuo de al lado sí debe seguir saliendo.
    """
    gaps = _vital_chain_gaps(_chain_db(tmp_path, plan_rows=51, plan_recent=False))
    reported = " ".join(gaps["sample"])

    assert "plan:" not in reported, gaps["sample"]
    assert any("worker" in linea for linea in gaps["sample"]), gaps["sample"]


def test_on_demand_stage_never_written_is_still_a_gap(tmp_path: Path) -> None:
    """Sin filas nunca no hay prueba de que el eslabón funcionara jamás."""
    gaps = _vital_chain_gaps(_chain_db(tmp_path, plan_rows=0, plan_recent=False))

    assert any(linea.startswith("plan: sin filas") for linea in gaps["sample"]), gaps[
        "sample"
    ]


def test_debt_report_says_unknown_instead_of_inventing(tmp_path: Path) -> None:
    report = build_debt_report(REPO_ROOT, None, tmp_path / "vacio", allow_build=False)
    assert report["status"] == "unknown"
    assert report["items"] == {}
    assert "no medible" in summarise_for_humans(report).lower()


def test_un_servicio_declarado_y_parado_es_deuda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El watchdog estaba escrito, inervado, declarado como servicio y parado.

    No aparecía en ninguna categoría: en el grafo de entrypoints salía `legacy`,
    un estado que se creó para no llamar deuda a 45 utilidades manuales y que de
    paso escondió los órganos de vigilancia. Una herramienta que se lanza a mano
    y un servicio declarado que no corre no se distinguen por si alguien los citó
    en un `.md`.
    """
    from triade.observability import introspection

    units = tmp_path / "deploy" / "systemd"
    units.mkdir(parents=True)
    (units / "triade-fantasma.service").write_text(
        "[Service]\nExecStart=/usr/bin/python scripts/no_existe_este_proceso.py\n",
        encoding="utf-8",
    )
    (units / "triade-viva.service").write_text(
        "[Service]\nExecStart=/usr/bin/python scripts/runtime_vivo.py\n",
        encoding="utf-8",
    )
    # El process table se fija: la prueba mide la comparación, no qué corre hoy
    # en esta máquina. Se compara por el argumento distintivo y no por la ruta
    # del intérprete, porque el runtime real arranca con otro binario de Python
    # y compararlo entero daría todo por parado.
    monkeypatch.setattr(
        introspection,
        "_running_commands",
        lambda: ["/otro/prefijo/bin/python scripts/runtime_vivo.py --flag"],
    )

    entry = introspection._declared_services_not_running(tmp_path, None)

    assert entry["count"] == 1, entry["sample"]
    assert "triade-fantasma.service" in entry["sample"][0]
    assert "/proc" in entry["evidence"]


def test_una_tabla_sin_lector_ni_escritor_sigue_siendo_deuda(tmp_path: Path) -> None:
    """Borrar al escritor no puede bajar la deuda: eso es degradar, no arreglar."""
    cache = tmp_path / "graphs"
    report = build_debt_report(REPO_ROOT, _db(tmp_path), cache, max_age_seconds=0)

    assert "tables_without_reader_or_writer" in report["items"]
    entry = report["items"]["tables_without_reader_or_writer"]
    assert entry["evidence"], "una categoría sin evidencia no mide nada"
    assert report["debt_items_total"] == sum(
        e["count"] for e in report["items"].values()
    )


def test_debt_endpoint_declares_la_edad_y_el_refresco(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La cifra no puede viajar sin decir de cuándo es ni si se está rehaciendo.

    Con `allow_build=False`, el informe describe artefactos que pueden llevar
    horas parados. Quien lo lee tiene que poder distinguir una medición de ahora
    de una de antes del último commit.
    """
    from apps.routes import ui as ui_routes

    refresher = GraphRefresher(REPO_ROOT, tmp_path / "graphs", stale_seconds=99999)
    monkeypatch.setattr(ui_routes, "REFRESHER", refresher)
    monkeypatch.setattr(ui_routes, "refresh_artifacts", lambda **_: "fresh")

    with TestClient(app) as client:
        payload = client.get("/api/internal-graphs/debt").json()

    refresh = payload["refresh"]
    assert refresh["trigger"] == "fresh"
    assert refresh["running"] is False
    assert "stale" in refresh and "stale_after_seconds" in refresh
    assert refresh["last_error"] is None
    if payload["status"] == "measured":
        assert payload["graphs_age_seconds"] >= 0


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


def test_un_servicio_sin_proceso_pero_con_efecto_no_es_deuda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La pregunta no es «¿corre este proceso?» sino «¿ocurre esta función?».

    El watchdog, los workers y el backup se cumplen como hilo o como tarea del
    proceso de la API, no como el servicio declarado. Exigir el proceso marcaba
    como parado algo que está pasando, y eso deja la categoría gritando para
    siempre: una alarma que nunca se puede apagar se aprende a ignorar.
    """
    from triade.observability import introspection

    units = tmp_path / "deploy" / "systemd"
    units.mkdir(parents=True)
    (units / "triade-watchdog.service").write_text(
        "[Service]\nExecStart=/usr/bin/python scripts/runtime_watchdog.py\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(introspection, "_running_commands", lambda: ["/bin/otra/cosa"])

    db = tmp_path / "triade.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE runtime_health_snapshots (created_at TEXT)")
    connection.execute(
        "INSERT INTO runtime_health_snapshots VALUES (?)",
        (datetime.now(UTC).isoformat(),),
    )
    connection.commit()
    connection.close()

    assert introspection._declared_services_not_running(tmp_path, db)["count"] == 0


def test_un_servicio_sin_proceso_y_sin_efecto_si_es_deuda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Medir por efecto no puede volverse una forma de no ver nada nunca."""
    from triade.observability import introspection

    units = tmp_path / "deploy" / "systemd"
    units.mkdir(parents=True)
    (units / "triade-watchdog.service").write_text(
        "[Service]\nExecStart=/usr/bin/python scripts/runtime_watchdog.py\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(introspection, "_running_commands", lambda: ["/bin/otra/cosa"])

    db = tmp_path / "triade.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE runtime_health_snapshots (created_at TEXT)")
    viejo = datetime.now(UTC) - timedelta(days=3)
    connection.execute(
        "INSERT INTO runtime_health_snapshots VALUES (?)", (viejo.isoformat(),)
    )
    connection.commit()
    connection.close()

    entry = introspection._declared_services_not_running(tmp_path, db)
    assert entry["count"] == 1
    assert "sin efecto reciente" in entry["sample"][0]


def test_las_tablas_internas_de_sqlite_no_son_deuda(tmp_path: Path) -> None:
    """`sqlite_sequence` la mantiene el motor: exigirle un escritor es un error."""
    from triade.observability.introspection import SQLITE_INTERNAL_TABLES

    cache = tmp_path / "graphs"
    report = build_debt_report(REPO_ROOT, _db(tmp_path), cache, max_age_seconds=0)

    huerfanas = report["items"]["tables_without_reader_or_writer"]["sample"]
    assert not (set(huerfanas) & SQLITE_INTERNAL_TABLES), huerfanas

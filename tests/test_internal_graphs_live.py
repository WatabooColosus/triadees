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
from triade.observability.event_feed import (
    FeedCursor,
    latest_cursor,
    read_new_events,
    read_recent_events,
)
from triade.observability.introspection import (
    _classify_with_contracts,
    _vital_chain_gaps,
    _writer_reachability,
    build_debt_report,
    summarise_for_humans,
    unexecuted_task_types,
)
from triade.observability.refresh import GraphRefresher
from triade.observability.runtime_graph import task_type_counts

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


def _worker_graph_artifact(destino: Path) -> Path:
    """Genera el grafo de workers con su constructor real.

    Sin esto la prueba dependía de `artifacts/internal_graphs/worker_graph.json`,
    que está en `.gitignore`: existía en la máquina de quien lo generó alguna vez
    y **no** en CI. La prueba salía verde en local y roja en CI —y así llegó a
    `main` el 2026-08-28, con `required-result` en rojo—. Una prueba cuyo
    resultado depende de un fichero sin versionar no prueba nada.
    """
    from dataclasses import asdict

    from triade.observability.runtime_graph import build_worker_graph

    # `internal_graphs_live.ROOT`, no `Path.cwd()`: `conftest` mueve el cwd a un
    # sandbox con cuatro enlaces simbólicos y sin `.github/workflows`, `Procfile`
    # ni `Dockerfile`. La alcanzabilidad se calcula desde ahí, sale vacía, ningún
    # contrato de activación se sostiene y `ready_when_idle` queda a cero —el
    # mismo síntoma que producía el artefacto ausente en CI, por otra causa—.
    # En producción el módulo usa esta misma raíz.
    nodes, _edges = build_worker_graph(internal_graphs_live.ROOT, db_path=None)
    destino.mkdir(parents=True, exist_ok=True)
    artefacto = destino / "worker_graph.json"
    artefacto.write_text(
        json.dumps({"nodes": [asdict(n) for n in nodes]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return artefacto


def test_pulse_carries_live_signals_not_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El pulso debe ser barato: relee SQLite, nunca el AST del repositorio."""
    monkeypatch.setenv("TRIADE_DB_PATH", str(_db(tmp_path)))
    artefactos = tmp_path / "internal_graphs"
    _worker_graph_artifact(artefactos)
    monkeypatch.setattr(internal_graphs_live, "ARTIFACT_DIR", artefactos)
    internal_graphs_live._cache.clear()

    pulse, _ = internal_graphs_live.build_pulse()

    assert pulse["simulated"] is False
    assert pulse["legend"], "el color viaja con el pulso para que la UI no lo invente"
    signals = pulse["signals"]
    assert "LIFE_PULSE" in signals["stages"]
    assert signals["readiness_source"] == "worker_graph_artifact"
    # Los tipos declarados sin una sola ejecución son justo lo que hay que ver.
    assert signals["task_types"]["pulse_check"]["executions"] == 1
    assert signals["task_types"]["goal_lora_train"]["executions"] == 0
    assert signals["task_types"]["goal_lora_train"]["state"] == "ready"


def test_sin_el_artefacto_el_pulso_dice_que_no_sabe_en_vez_de_inventar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Falta el grafo de workers: eso es ignorancia, no desconexión.

    Antes el conjunto de `ready_when_idle` quedaba vacío en silencio y un tipo
    humano-gateado salía `disconnected` —«no está conectado»— cuando la verdad
    era «no he podido mirarlo».
    """
    monkeypatch.setenv("TRIADE_DB_PATH", str(_db(tmp_path)))
    monkeypatch.setattr(internal_graphs_live, "ARTIFACT_DIR", tmp_path / "sin-nada")
    internal_graphs_live._cache.clear()

    signals = internal_graphs_live.build_pulse()[0]["signals"]

    assert signals["readiness_source"] == "missing"
    assert signals["task_types"]["goal_lora_train"]["state"] == "unknown"
    # Lo que sí se midió sigue midiéndose: la ignorancia es sólo del readiness.
    assert signals["task_types"]["pulse_check"]["executions"] == 1


def test_timeline_reads_persisted_history_without_changing_sse_cursor(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO worker_events "
            "(run_ref,task_id,task_type,event_type,status,created_at) "
            "VALUES ('run-visible','task-visible','pulse_check',"
            "'task_completed','ok','2026-08-10T01:00:00+00:00')"
        )
    before = latest_cursor(db)

    events = read_recent_events(db, run_id="run-visible", limit=10)
    after = latest_cursor(db)

    assert before.positions == after.positions
    assert len(events) == 1
    assert events[0]["evidence"].startswith("sqlite:worker_events.id=")
    assert events[0]["data"]["run_ref"] == "run-visible"


def test_global_graph_search_returns_canonical_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_graph(name: str, limit: int | None = None) -> dict[str, object]:
        del limit
        nodes = (
            [
                {
                    "node_id": "task_type:learning_evidence_generation",
                    "label": "learning_evidence_generation",
                    "kind": "task_type",
                    "state": "active",
                    "metadata": {"evidence": "sqlite:autonomous_tasks"},
                }
            ]
            if name == "workers"
            else []
        )
        return {"nodes": nodes, "edges": [], "states": {}}

    monkeypatch.setattr(internal_graphs_live, "build_graph", fake_graph)

    result = internal_graphs_live.search_system("evidence_generation")

    assert result["simulated"] is False
    assert result["results"] == [
        {
            "graph": "workers",
            "node_id": "task_type:learning_evidence_generation",
            "label": "learning_evidence_generation",
            "kind": "task_type",
            "state": "active",
            "evidence": "sqlite:autonomous_tasks",
        }
    ]


def test_administrative_entrypoint_stays_visible_but_not_real_debt(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "graphs"
    cache.mkdir()
    (cache / "entrypoint_graph.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "node_id": "entrypoint:scripts/tool.py",
                        "label": "scripts/tool.py",
                        "metadata": {
                            "path": "scripts/tool.py",
                            "launchers": 0,
                            "activation": "administrative_on_demand",
                            "activation_evidence": "argparse --apply gate + rollback option",
                        },
                        "state": "disconnected",
                    }
                ],
                "edges": [],
                "metadata": {"generated_at": datetime.now(UTC).isoformat()},
            }
        ),
        encoding="utf-8",
    )
    entrypoints = {
        "count": 1,
        "items": ["scripts/tool.py"],
        "sample": ["scripts/tool.py"],
    }
    items = {"entrypoints_without_launcher": entrypoints}

    counts = _classify_with_contracts(REPO_ROOT, items, {}, None, cache_dir=cache)

    assert entrypoints["count"] == 1
    verdict = entrypoints["classified"]["scripts/tool.py"]
    assert verdict["classification"] == "ON_DEMAND"
    assert verdict["contract_holds"] is True
    assert counts["ON_DEMAND"] == 1
    assert counts["REAL_BROKEN"] == 0


def test_manual_diagnostic_stays_visible_as_manual_tool(tmp_path: Path) -> None:
    cache = tmp_path / "graphs"
    cache.mkdir()
    (cache / "entrypoint_graph.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "node_id": "entrypoint:scripts/stress.py",
                        "label": "scripts/stress.py",
                        "metadata": {
                            "path": "scripts/stress.py",
                            "launchers": 0,
                            "activation": "manual_diagnostic",
                            "activation_evidence": "bounded diagnostic CLI",
                        },
                        "state": "disconnected",
                    }
                ],
                "edges": [],
                "metadata": {"generated_at": datetime.now(UTC).isoformat()},
            }
        ),
        encoding="utf-8",
    )
    entrypoints = {
        "count": 1,
        "items": ["scripts/stress.py"],
        "sample": ["scripts/stress.py"],
    }

    counts = _classify_with_contracts(
        REPO_ROOT,
        {"entrypoints_without_launcher": entrypoints},
        {},
        None,
        cache_dir=cache,
    )

    verdict = entrypoints["classified"]["scripts/stress.py"]
    assert verdict["classification"] == "MANUAL_TOOL"
    assert counts == {"MANUAL_TOOL": 1, "REAL_BROKEN": 0}


def test_declared_manual_entrypoint_classifies_its_module_chain(tmp_path: Path) -> None:
    cache = tmp_path / "graphs"
    cache.mkdir()
    (cache / "entrypoint_graph.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "node_id": "entrypoint:scripts/verify.py",
                        "label": "scripts/verify.py",
                        "metadata": {
                            "path": "scripts/verify.py",
                            "launchers": 0,
                            "activation": "manual_diagnostic",
                            "activation_evidence": (
                                "declared:TRIADE_ENTRYPOINT_KIND=manual_diagnostic"
                            ),
                        },
                    }
                ],
                "edges": [],
            }
        ),
        encoding="utf-8",
    )
    (cache / "import_graph.json").write_text(
        json.dumps(
            {
                "nodes": [],
                "edges": [
                    {
                        "source": "module:scripts/verify.py",
                        "target": "module:triade/evaluation/check.py",
                        "relation": "imports",
                    },
                    {
                        "source": "module:triade/evaluation/check.py",
                        "target": "module:triade/evaluation/metric.py",
                        "relation": "imports",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    modules = {
        "count": 2,
        "items": [
            "triade/evaluation/check.py",
            "triade/evaluation/metric.py",
        ],
        "sample": [],
    }

    counts = _classify_with_contracts(
        REPO_ROOT,
        {"modules_unreachable_from_entrypoint": modules},
        {},
        None,
        cache_dir=cache,
    )

    assert counts == {"MANUAL_TOOL": 2, "REAL_BROKEN": 0}
    assert set(modules["classified"]) == set(modules["items"])
    assert (
        modules["classified"]["triade/evaluation/metric.py"]["evidence"][0][
            "entrypoint"
        ]
        == "scripts/verify.py"
    )


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


def test_sse_cursor_roundtrip_and_bounded_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El stream cierra solo y el navegador puede reanudar sin saltos."""
    initial = FeedCursor({"worker_events": 41, "runs": 7})
    advanced = FeedCursor({"worker_events": 42, "runs": 7})

    monkeypatch.setattr(
        internal_graphs_live,
        "build_pulse",
        lambda cursor: ({"cursor": advanced.to_dict()}, advanced),
    )

    chunks = list(
        internal_graphs_live.event_stream(
            cursor=initial,
            interval_seconds=0,
            max_lifetime_seconds=0,
        )
    )

    assert len(chunks) == 1
    event_id = chunks[0].splitlines()[0].removeprefix("id: ")
    assert internal_graphs_live.decode_stream_cursor(event_id) == advanced
    assert internal_graphs_live.decode_stream_cursor("no-es-base64") is None


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


def test_debt_report_reuses_the_published_alias_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una lectura caliente no puede volver a recorrer todo el repositorio."""
    from triade.observability import introspection

    cache = tmp_path / "graphs"
    db = _db(tmp_path)
    build_debt_report(REPO_ROOT, db, cache, max_age_seconds=0)

    def unexpected_scan(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("el análisis de alias ya estaba publicado")

    monkeypatch.setattr(introspection, "build_alias_debt", unexpected_scan)
    report = build_debt_report(REPO_ROOT, db, cache, max_age_seconds=3600)

    assert report["status"] == "measured"


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


def test_system_graph_aggregates_only_real_canonical_nodes() -> None:
    graph = internal_graphs_live.build_graph("system")

    assert graph["source"] == "canonical_graph_aggregation"
    assert graph["simulated"] is False
    assert graph["nodes"]
    for node in graph["nodes"]:
        assert node["metadata"]["matched_nodes"] > 0
        assert node["metadata"]["evidence_nodes"]
        assert (
            node["metadata"]["progressive_view"] in internal_graphs_live.GRAPH_BUILDERS
        )
    known = {node["node_id"] for node in graph["nodes"]}
    assert all(
        edge["source"] in known and edge["target"] in known for edge in graph["edges"]
    )


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


# --- El detector no puede contar la misma tabla dos veces ---------------------


def test_una_tabla_vacia_se_cuenta_una_sola_vez(tmp_path: Path) -> None:
    """`orphan_reader` y `tables_with_writer_and_no_rows` miden lo mismo.

    La primera marca «0 filas y al menos un lector»; la segunda, «0 filas y al
    menos un escritor». Casi toda tabla vacía cumple las dos, así que el total
    las sumaba dos veces: medido el 2026-08-07, 19 de 20 elementos de cada
    categoría eran la misma tabla, y 40 problemas eran en realidad 21.
    """
    report = build_debt_report(
        REPO_ROOT, _db(tmp_path), tmp_path / "g", max_age_seconds=0
    )
    items = report["items"]
    contadas = (
        set(items["tables_with_writer_and_no_rows"]["items"])
        | set(items["tables_without_reader_or_writer"]["items"])
        | set(items["tables_written_never_read"]["items"])
    )

    for senal in ("alias_debt_orphan_reader", "alias_debt_lexical_alias"):
        repetidas = contadas & set(items[senal]["items"])
        assert not repetidas, f"{senal} vuelve a contar tablas ya contadas: {repetidas}"

    assert report["debt_items_total"] == sum(e["count"] for e in items.values())


def test_lo_no_contado_sigue_visible_con_su_diagnostico(tmp_path: Path) -> None:
    """Dejar de contar no puede ser dejar de informar.

    Quien audite una tabla vacía necesita saber si además tiene un lector
    huérfano; lo que sobra es el recuento repetido, no el diagnóstico.
    """
    report = build_debt_report(
        REPO_ROOT, _db(tmp_path), tmp_path / "g", max_age_seconds=0
    )
    entrada = report["items"]["alias_debt_orphan_reader"]

    assert "also_counted_elsewhere" in entrada
    assert entrada["also_counted_elsewhere"], "ninguna tabla quedó registrada"
    assert "ya contadas" in entrada["evidence"]


def test_alias_vacio_cacheado_se_invalida_con_filas_vivas(tmp_path: Path) -> None:
    """La evidencia temporal viva prevalece sobre un artefacto estructural viejo."""
    db = _db(tmp_path)
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE learned_events (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO learned_events VALUES (1)")

    cache = tmp_path / "graphs"
    cache.mkdir()
    (cache / "index.json").write_text("{}", encoding="utf-8")
    (cache / "alias_debt.json").write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "signal": "orphan_reader",
                        "kind": "table",
                        "dead": "learned_events",
                    },
                    {
                        "signal": "lexical_alias",
                        "kind": "table",
                        "dead": "learned_events",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    report = build_debt_report(REPO_ROOT, db, cache, allow_build=False)

    assert report["items"]["alias_debt_orphan_reader"]["count"] == 0
    assert report["items"]["alias_debt_lexical_alias"]["count"] == 0


# --- Quién escribe una tabla vacía, y si puede llegar a ejecutarse ------------


def _cache_sintetica(tmp_path: Path) -> Path:
    """Artefactos mínimos: un entrypoint lanzado, un import, y tres escritores."""
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "entrypoint_graph.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {"metadata": {"path": "apps/app.py", "launchers": 1}},
                    {"metadata": {"path": "scripts/suelto.py", "launchers": 0}},
                ]
            }
        ),
        encoding="utf-8",
    )
    (cache / "import_graph.json").write_text(
        json.dumps(
            {
                "edges": [
                    {
                        "relation": "imports",
                        "source": "module:apps/app.py",
                        "target": "module:triade/vivo.py",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (cache / "table_graph.json").write_text(
        json.dumps(
            {
                "edges": [
                    {
                        "relation": "writes",
                        "source": "module:triade/vivo.py",
                        "target": "table:conectada",
                    },
                    {
                        "relation": "writes",
                        "source": "module:scripts/suelto.py",
                        "target": "table:huerfana",
                    },
                    {
                        "relation": "writes",
                        "source": "module:tests/test_algo.py",
                        "target": "table:solo_en_pruebas",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return cache


def test_distingue_escritor_alcanzable_de_escritor_muerto(tmp_path: Path) -> None:
    """«Tiene escritor y cero filas» esconde dos casos opuestos.

    Uno que el runtime nunca puede alcanzar —la capacidad no existe— y uno
    perfectamente alcanzable cuyo evento no ha ocurrido —ausencia de estímulo,
    no deuda—. Sin separarlos, triar una tabla exige reinvestigarla entera.
    """
    veredictos = _writer_reachability(
        _cache_sintetica(tmp_path),
        ["conectada", "huerfana", "solo_en_pruebas", "sin_nadie"],
    )

    assert veredictos["conectada"]["verdict"] == "escritor_alcanzable"
    assert veredictos["conectada"]["reachable_writers"] == ["triade/vivo.py"]
    assert veredictos["huerfana"]["verdict"] == "escritor_inalcanzable"
    assert veredictos["huerfana"]["reachable_writers"] == []
    # El unico escritor de `goals` en el repositorio real es un test: la tabla
    # figuraba como «el escritor existe» sin tener ninguno en produccion.
    assert veredictos["solo_en_pruebas"]["verdict"] == "solo_tests"
    assert veredictos["sin_nadie"]["verdict"] == "sin_escritor_en_codigo"


def test_encolar_no_es_ejecutar(tmp_path: Path) -> None:
    """Un tipo atascado en `pending` no puede figurar como ejecutado.

    `task_type_counts` contaba todas las filas de la cola, asi que un tipo
    encolado una vez y nunca atendido desaparecia de
    `task_types_never_executed`. Visto el 2026-08-08 con
    `stable_consolidation_review`: se encolo por primera vez en la historia del
    sistema, seguia en `pending` con `attempt=0`, y el informe ya lo daba por
    corrido. Un contador que confunde intencion con efecto no mide nada.
    """
    db = tmp_path / "cola.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE autonomous_tasks (task_id TEXT, task_type TEXT, status TEXT)"
        )
        conn.executemany(
            "INSERT INTO autonomous_tasks VALUES (?,?,?)",
            [
                ("a", "esperando", "pending"),
                ("e", "en_vuelo", "running"),
                ("b", "corrio", "completed"),
                ("c", "miro_y_no_actuo", "observed"),
                ("d", "fallo", "dead_letter"),
            ],
        )

    counts = task_type_counts(db)

    assert counts.get("esperando", 0) == 0, "encolar no es ejecutar"
    assert counts["corrio"] == 1
    # `running` si cuenta: la tarea fue reclamada y el handler esta dentro.
    assert counts["en_vuelo"] == 1
    # El handler llego a decidir, aunque decidiera no actuar o fallara.
    assert counts["miro_y_no_actuo"] == 1
    assert counts["fallo"] == 1

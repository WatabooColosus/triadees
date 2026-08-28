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
import os
import time
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from triade.db import sqlite3

from .activation_contracts import ContractVerifier, load_contracts
from .alias_debt import build_alias_debt, profiles_from_artifact
from .runtime_graph import (
    ON_DEMAND_STAGES,
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
#: Tablas que mantiene SQLite y que ningún código debe tocar.
SQLITE_INTERNAL_TABLES = frozenset({"sqlite_sequence", "sqlite_stat1", "sqlite_stat4"})


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
    try:
        graph_builder = import_module("scripts.build_internal_graphs")
    except ModuleNotFoundError as exc:
        # ``python scripts/triage_debt.py`` pone ``scripts/`` —no la raíz— al
        # frente de sys.path. Esa es la invocación documentada y debe poder
        # regenerar un cache vacío igual que ``python -m scripts.triage_debt``.
        if exc.name != "scripts":
            raise
        graph_builder = import_module("build_internal_graphs")

    graph_builder.build_all(root, db_path, cache_dir, render=False)
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

    #: Tablas ya contadas por las categorías de `table_graph`. Las señales de
    #: alias que hablan de la misma tabla no vuelven a sumarla: ver
    #: `_alias_table_entry`.
    tablas_ya_contadas: set[str] = set()

    tables = _load(cache_dir, "table_graph")
    if tables:
        nodes = [n for n in tables["nodes"] if n["node_id"].startswith("table:")]
        write_only, never_written, abandoned = [], [], []
        for node in nodes:
            rows = rows_by_table.get(node["label"])
            if rows is None:
                continue
            readers = node["metadata"].get("readers", 0)
            writers = node["metadata"].get("writers", 0)
            if node["label"] in SQLITE_INTERNAL_TABLES:
                # `sqlite_sequence` la mantiene el propio motor para las columnas
                # `AUTOINCREMENT`. Que ningún código la nombre es lo correcto:
                # contarla como deuda es pedirle al repositorio que gestione algo
                # que no es suyo.
                continue
            if readers == 0 and writers == 0:
                abandoned.append(node["label"])
            elif rows > 0 and readers == 0 and writers > 0:
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
        # El recuento no cambia: lo que se añade es el veredicto que permite
        # triar cada tabla sin volver a investigarla desde cero.
        items["tables_with_writer_and_no_rows"]["writer_reachability"] = (
            _writer_reachability(cache_dir, never_written)
        )
        # Sin esta categoría la deuda se podía reducir borrando al escritor.
        # `benchmark_results`, `benchmark_tasks` y `federated_merge_log` salieron
        # del recuento el 2026-08-03 al quedarse sin escritor, sin haber ganado
        # una sola fila: salieron por degradación (F-034). Una tabla que existe
        # en la base y a la que ya no apunta ningún código sigue siendo deuda, y
        # además es la única que nadie iba a echar de menos.
        items["tables_without_reader_or_writer"] = _entry(
            abandoned,
            "table_graph.json: tabla viva sin lector ni escritor en el código",
        )
        tablas_ya_contadas = set(write_only) | set(never_written) | set(abandoned)

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

        # Un escalón más sutil que el anterior, y el que de verdad escondía
        # denervación: el módulo **sí** tiene importador, pero es su propio
        # test. Eso demuestra que el código corre, no que participe en ninguna
        # cadena — y como el grafo lo pintaba `active`, ni aparecía.
        # Se excluyen los `__init__.py`, que Python ejecuta al importar
        # cualquier submódulo, y los entrypoints, que se arrancan en vez de
        # importarse y ya los cuenta `entrypoints_without_launcher`.
        #
        # Y se mira sólo `triade/`, no `apps/`. No es una lista de exclusión:
        # es el alcance de lo que este grafo puede ver. A una app la arranca una
        # configuración de despliegue —`render.yaml` levanta
        # `uvicorn apps.public_relay_app:app`— y eso no es un import de Python,
        # así que aquí no hay forma de distinguir la app servida de la
        # abandonada. Contarlas produciría falsos positivos sobre superficie de
        # producción real. Cuando el grafo lea configuración de despliegue,
        # `apps/` entra aquí sin más cambios.
        entrypoint_paths = {
            str(n["metadata"].get("path", ""))
            for n in (_load(cache_dir, "entrypoint_graph") or {}).get("nodes", [])
            if str(n.get("node_id", "")).startswith("entrypoint:")
        }
        solo_tests = [
            ruta
            for n in imports["nodes"]
            if n["metadata"].get("only_test_importers")
            and (ruta := str(n["metadata"].get("path", ""))).startswith("triade/")
            and not ruta.endswith("__init__.py")
            and ruta not in entrypoint_paths
        ]
        items["modules_imported_only_by_tests"] = _entry(
            solo_tests,
            "import_graph.json: módulo de producción cuyo único importador es un test",
        )

        # El escalón que faltaba, y por el que se colaron 35 módulos.
        #
        # Las dos categorías de arriba miran *quién importa*. Una isla de
        # módulos que se importan **entre sí** las pasa las dos: cada uno tiene
        # importador y ninguno es un test. Medido el 2026-08-27: el informe
        # daba `modules_without_importer: 0` mientras `triade/dashboard/` y
        # `triade/os/triadeos_complete.py` —un gemelo del TriadeOS que sí corre,
        # 304 ciclos al día desde `services/supervisor.py`— estaban
        # desconectados del sistema entero, y con ellos los únicos consumidores
        # de `SystemMonitor`, `ConstitutionEnforcer`, `AdvancedScheduler`,
        # `FederationAdvanced`, `SmartModelRouter` y cinco más.
        #
        # Lo que separa «alguien lo importa» de «el sistema lo conecta» es la
        # alcanzabilidad desde un entrypoint que **algo arranca**, y esa función
        # ya existía: `reachable_modules` la usa `triage_debt.py` para decidir
        # si el escritor de una tabla es alcanzable. Aquí no se usaba.
        #
        # Se excluyen los `__init__.py`: Python los ejecuta al importar
        # cualquier submódulo, así que un paquete vivo tiene su `__init__`
        # «inalcanzable» sin que eso signifique nada.
        # La reconstrucción ya publicó exactamente los módulos y sus imports.
        # Releer aquí los ~900 AST hacía que una consulta interactiva de deuda
        # tardara decenas de segundos aun con artefactos frescos, y el worker
        # ``system_debt_scan`` podía expirar haciendo el mismo trabajo dos veces.
        # La alcanzabilidad se deriva del mismo artefacto que alimenta el panel.
        alcanzables = _reachable_paths_from_artifacts(cache_dir)
        rutas_publicadas = {
            str(nodo.get("metadata", {}).get("path", ""))
            for nodo in imports.get("nodes", ())
        }
        islas = (
            sorted(
                ruta
                for ruta in rutas_publicadas
                if ruta.startswith("triade/")
                and ruta not in alcanzables
                and not ruta.endswith("__init__.py")
            )
            if alcanzables is not None
            else []
        )
        items["modules_unreachable_from_entrypoint"] = _entry(
            islas,
            "import_graph.json + entrypoint_graph.json: módulo que ningún entrypoint arrancado alcanza",
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
    # Deuda de alias: el lector que apunta al gemelo muerto de lo que sí se
    # escribe. Es la forma que tenían **todos** los cortes de la auditoría del
    # 2026-08-03, y cada uno costó una auditoría manual para salir. Entra aquí y
    # no en una ruta aparte porque este informe es la medición única que leen la
    # API y el worker `system_debt_scan`: si el detector viviera fuera, sería un
    # órgano más sin quien lo consulte —justo lo que detecta—.
    #
    # Se le pasan los perfiles del artefacto ya generado: reconstruir el grafo de
    # tablas cuesta una relectura completa del AST y este informe se sirve en
    # caliente.
    alias = _load(cache_dir, "alias_debt")
    if alias is None:
        # Compatibilidad con artefactos anteriores. Esta ruta sólo se paga una
        # vez durante una transición; el build actual siempre publica el alias.
        alias = build_alias_debt(
            root,
            table_profiles=profiles_from_artifact(_load(cache_dir, "table_graph")),
        )
    # Los artefactos conservan la estructura, pero sus contadores de filas son
    # una fotografía. Una tabla puede recibir filas después del build; en ese
    # caso las señales cuya premisa es ``rows == 0`` quedan refutadas por la DB
    # viva y no deben seguir sumando deuda hasta el siguiente refresh.
    alias_findings = [
        finding
        for finding in alias["findings"]
        if not (
            finding.get("kind") == "table"
            and finding.get("signal") in {"orphan_reader", "lexical_alias"}
            and int(rows_by_table.get(str(finding.get("dead")), 0)) > 0
        )
    ]
    # `suspected_dead_status` entra igual que los demás: rebajar la confianza de
    # un hallazgo no es motivo para esconderlo del contador.
    for senal in (
        "orphan_reader",
        "lexical_alias",
        "dead_status_value",
        "suspected_dead_status",
    ):
        hallazgos = [h for h in alias_findings if h["signal"] == senal]
        items[f"alias_debt_{senal}"] = _alias_table_entry(
            senal, hallazgos, tablas_ya_contadas
        )
    items["declared_services_not_running"] = _declared_services_not_running(
        root, db_path
    )
    items["backup_protection_gaps"] = _backup_protection_gaps(root)

    items["vital_chain_gaps"] = _vital_chain_gaps(db_path)

    # Inactividad legítima frente a rotura. Hasta aquí toda ausencia de actividad
    # pesa igual, y eso hace daño en los dos sentidos: una tabla que espera una
    # firma humana que nadie ha dado sube el contador como si estuviera rota, y
    # una rotura real se pierde entre ellas.
    #
    # La separación **no** sale de una lista de nombres: sale de contratos que
    # declaran su evidencia estructural y que se vuelven a comprobar aquí, en
    # cada medición. Lo que no tiene contrato, o lo tiene y no se sostiene, sigue
    # siendo `REAL_BROKEN`. Ver `activation_contracts.py`.
    clasificado = _classify_with_contracts(
        root, items, rows_by_table, db_path, cache_dir=cache_dir
    )
    real = sum(
        entry["count"] - len(entry.get("classified", {})) for entry in items.values()
    )

    return {
        "status": "measured",
        # `debt_items_total` sigue siendo la suma de todo lo observado: bajar el
        # número escondiendo categorías sería exactamente lo que este informe
        # existe para impedir. Lo que se añade es de cuánto de eso hay que
        # ocuparse hoy.
        "debt_items_total": sum(entry["count"] for entry in items.values()),
        "debt_real_total": real,
        "formula": (
            "debt_items_total = suma de count de cada categoría; "
            "debt_real_total = lo mismo menos lo que tiene contrato verificado"
        ),
        "by_classification": clasificado,
        "graphs_generated_at": generated_at,
        "graphs_age_seconds": round(time.time() - generated_at, 1),
        "items": items,
        "simulated": False,
    }


def _classify_with_contracts(
    root: Path,
    items: dict[str, Any],
    rows_by_table: dict[str, int],
    db_path: Path | None,
    *,
    cache_dir: Path = DEFAULT_CACHE,
) -> dict[str, int]:
    """Aplica los contratos y anota en cada categoría lo que sale del contador.

    Devuelve el recuento por clasificación, incluida `REAL_BROKEN`, para que el
    panel pueda enseñarlas separadas sin que ninguna desaparezca. Un contrato que
    no se sostiene no clasifica: deja constancia de qué evidencia se cayó y el
    sujeto se queda donde estaba.
    """
    contratos = load_contracts()
    if not contratos:
        return {}
    verificador = ContractVerifier(
        root,
        table_profiles={
            tabla: {"rows": filas} for tabla, filas in rows_by_table.items()
        },
        db_path=db_path,
        reachable=_reachable_paths_from_artifacts(cache_dir),
    )
    recuento: dict[str, int] = {}
    entrypoints = _load(cache_dir, "entrypoint_graph") or {}
    administrative = {
        str(node.get("label") or ""): node.get("metadata") or {}
        for node in entrypoints.get("nodes", ())
        if (node.get("metadata") or {}).get("activation") == "administrative_on_demand"
    }
    manual_diagnostics = {
        str(node.get("label") or ""): node.get("metadata") or {}
        for node in entrypoints.get("nodes", ())
        if (node.get("metadata") or {}).get("activation") == "manual_diagnostic"
    }
    manual_module_routes = _declared_manual_module_reachability(cache_dir)
    for categoria, entry in items.items():
        if not entry.get("count"):
            continue
        prefijo = "task_type" if categoria == "task_types_never_executed" else "table"
        clasificados: dict[str, Any] = {}
        rotos: dict[str, Any] = {}
        for nombre in entry.get("items", entry.get("sample", [])):
            if (
                categoria == "modules_unreachable_from_entrypoint"
                and nombre in manual_module_routes
            ):
                routes = manual_module_routes[nombre]
                classifications = {route["classification"] for route in routes}
                classification = (
                    "ON_DEMAND"
                    if classifications == {"ON_DEMAND"}
                    else "MANUAL_TOOL"
                )
                clasificados[nombre] = {
                    "subject": f"module:{nombre}",
                    "classification": classification,
                    "reason": (
                        "Módulo de soporte alcanzable desde una herramienta "
                        "manual declarada; no forma parte del runtime continuo"
                    ),
                    "contract_holds": True,
                    "failed_evidence": [],
                    "evidence": routes,
                }
                recuento[classification] = recuento.get(classification, 0) + 1
                continue
            if categoria == "entrypoints_without_launcher" and nombre in administrative:
                metadata = administrative[nombre]
                clasificados[nombre] = {
                    "subject": f"entrypoint:{nombre}",
                    "classification": "ON_DEMAND",
                    "reason": "CLI administrativa reversible con escritura opt-in",
                    "contract_holds": True,
                    "failed_evidence": [],
                    "evidence": metadata.get("activation_evidence"),
                }
                recuento["ON_DEMAND"] = recuento.get("ON_DEMAND", 0) + 1
                continue
            if (
                categoria == "entrypoints_without_launcher"
                and nombre in manual_diagnostics
            ):
                metadata = manual_diagnostics[nombre]
                clasificados[nombre] = {
                    "subject": f"entrypoint:{nombre}",
                    "classification": "MANUAL_TOOL",
                    "reason": "Diagnóstico manual acotado; no es un daemon ni runtime",
                    "contract_holds": True,
                    "failed_evidence": [],
                    "evidence": metadata.get("activation_evidence"),
                }
                recuento["MANUAL_TOOL"] = recuento.get("MANUAL_TOOL", 0) + 1
                continue
            contrato = contratos.get(f"{prefijo}:{nombre}")
            if contrato is None:
                continue
            veredicto = verificador.verify(contrato)
            if veredicto.holds:
                clasificados[nombre] = veredicto.to_dict()
                recuento[veredicto.classification] = (
                    recuento.get(veredicto.classification, 0) + 1
                )
            else:
                rotos[nombre] = veredicto.to_dict()
        if clasificados:
            entry["classified"] = clasificados
        if rotos:
            entry["contract_broken"] = rotos
    recuento["REAL_BROKEN"] = sum(
        entry["count"] - len(entry.get("classified", {})) for entry in items.values()
    )
    return recuento


def _declared_manual_module_reachability(
    cache_dir: Path,
) -> dict[str, list[dict[str, str]]]:
    """Módulos que pertenecen a CLIs manuales declaradas explícitamente.

    Un ``__main__`` o una mención en documentación no bastan: el entrypoint debe
    declarar ``TRIADE_ENTRYPOINT_KIND`` con el vocabulario cerrado que publica
    ``code_graph``. Desde él se sigue el grafo de imports publicado. Si se borra
    la declaración o se corta el import, el módulo deja de clasificar en el
    siguiente build y vuelve automáticamente a ``REAL_BROKEN``.
    """
    imports = _load(cache_dir, "import_graph") or {}
    entrypoints = _load(cache_dir, "entrypoint_graph") or {}
    if not imports or not entrypoints:
        return {}

    adjacency: dict[str, set[str]] = {}
    for edge in imports.get("edges", ()):
        if edge.get("relation") != "imports":
            continue
        source = str(edge.get("source", "")).removeprefix("module:")
        target = str(edge.get("target", "")).removeprefix("module:")
        if source and target:
            adjacency.setdefault(source, set()).add(target)

    routes: dict[str, list[dict[str, str]]] = {}
    for node in entrypoints.get("nodes", ()):
        metadata = node.get("metadata") or {}
        activation = str(metadata.get("activation") or "")
        evidence = str(metadata.get("activation_evidence") or "")
        if activation not in {"administrative_on_demand", "manual_diagnostic"}:
            continue
        # Sólo una decisión explícita en el propio script puede clasificar sus
        # dependencias. Las heurísticas sirven para mostrar un entrypoint, no
        # para sacar una isla entera del contador de deuda.
        if not evidence.startswith("declared:TRIADE_ENTRYPOINT_KIND="):
            continue
        root = str(metadata.get("path") or node.get("label") or "")
        if not root:
            continue
        reached: set[str] = set()
        pending = list(adjacency.get(root, ()))
        while pending:
            current = pending.pop()
            if current in reached:
                continue
            reached.add(current)
            pending.extend(adjacency.get(current, ()))
        classification = (
            "ON_DEMAND"
            if activation == "administrative_on_demand"
            else "MANUAL_TOOL"
        )
        for module in reached:
            if not module.startswith("triade/"):
                continue
            routes.setdefault(module, []).append(
                {
                    "entrypoint": root,
                    "classification": classification,
                    "activation_evidence": evidence,
                }
            )
    return {
        module: sorted(found, key=lambda route: route["entrypoint"])
        for module, found in routes.items()
    }


def _reachable_paths_from_artifacts(cache_dir: Path) -> set[str] | None:
    """Deriva módulos alcanzables de los grafos ya publicados, sin releer AST."""
    imports = _load(cache_dir, "import_graph") or {}
    entrypoints = _load(cache_dir, "entrypoint_graph") or {}
    if not imports or not entrypoints:
        return None

    adjacency: dict[str, set[str]] = {}
    for edge in imports.get("edges", ()):
        source = str(edge.get("source", "")).removeprefix("module:")
        target = str(edge.get("target", "")).removeprefix("module:")
        if source and target:
            adjacency.setdefault(source, set()).add(target)

    pending = [
        str(node.get("metadata", {}).get("path", ""))
        for node in entrypoints.get("nodes", ())
        if int(node.get("metadata", {}).get("launchers", 0) or 0) > 0
    ]
    reachable: set[str] = set()
    while pending:
        path = pending.pop()
        if not path or path in reachable:
            continue
        reachable.add(path)
        pending.extend(adjacency.get(path, ()))
    return reachable


def _writer_reachability(
    cache_dir: Path, tablas: list[str]
) -> dict[str, dict[str, Any]]:
    """¿Quién escribe cada tabla vacía, y puede ese escritor llegar a ejecutarse?

    Sin esto, «tiene escritor y cero filas» no distingue dos cosas opuestas: un
    escritor que el runtime nunca puede alcanzar —deuda real, la capacidad no
    existe— y uno perfectamente alcanzable cuyo evento simplemente no ha
    ocurrido —ausencia de estímulo, no deuda—. `AliasFinding` reserva
    `reachable_writer` para esta respuesta y nadie la rellenaba nunca.

    El caso que lo motivó: el único escritor de `goals` es
    `tests/test_consciousness.py`. La tabla figuraba como «el escritor existe»
    cuando en producción no existe ninguno.

    Se calcula sobre los artefactos ya generados —adyacencia de imports y
    entrypoints con lanzador— porque este informe se sirve en caliente y
    reconstruir el AST costaría más que el trabajo que evalúa.
    """
    imports = _load(cache_dir, "import_graph") or {}
    entrypoints = _load(cache_dir, "entrypoint_graph") or {}
    tabla_graph = _load(cache_dir, "table_graph") or {}
    if not (imports and entrypoints and tabla_graph):
        return {}

    adyacencia: dict[str, set[str]] = {}
    for arista in imports.get("edges", ()):
        if arista.get("relation") != "imports":
            continue
        origen = str(arista.get("source", "")).partition(":")[2]
        destino = str(arista.get("target", "")).partition(":")[2]
        adyacencia.setdefault(origen, set()).add(destino)

    alcanzados = {
        str(nodo["metadata"].get("path") or "")
        for nodo in entrypoints.get("nodes", ())
        if int(nodo.get("metadata", {}).get("launchers") or 0) > 0
    } - {""}
    cola = list(alcanzados)
    while cola:
        actual = cola.pop()
        for destino in adyacencia.get(actual, ()):
            if destino not in alcanzados:
                alcanzados.add(destino)
                cola.append(destino)

    escritores: dict[str, set[str]] = {}
    for arista in tabla_graph.get("edges", ()):
        if arista.get("relation") != "writes":
            continue
        tabla = str(arista.get("target", "")).partition(":")[2]
        escritores.setdefault(tabla, set()).add(
            str(arista.get("source", "")).partition(":")[2]
        )

    veredictos: dict[str, dict[str, Any]] = {}
    for tabla in tablas:
        modulos = sorted(escritores.get(tabla, set()))
        produccion = [m for m in modulos if not m.startswith("tests/")]
        vivos = [m for m in produccion if m in alcanzados]
        if not produccion:
            veredicto = "solo_tests" if modulos else "sin_escritor_en_codigo"
        elif vivos:
            veredicto = "escritor_alcanzable"
        else:
            veredicto = "escritor_inalcanzable"
        veredictos[tabla] = {
            "verdict": veredicto,
            "writers": modulos[:5],
            "reachable_writers": vivos[:5],
        }
    return veredictos


def _alias_table_entry(
    senal: str, hallazgos: list[dict[str, Any]], ya_contadas: set[str]
) -> dict[str, Any]:
    """Una señal de alias, sin volver a sumar tablas que ya cuenta `table_graph`.

    `orphan_reader` marca «0 filas y al menos un lector».
    `tables_with_writer_and_no_rows` marca «0 filas y al menos un escritor».
    La inmensa mayoría de las tablas vacías cumplen las dos, así que el total
    las contaba dos veces: medido el 2026-08-07, **19 de 20** elementos de cada
    categoría eran la misma tabla. Sumadas daban 40 problemas donde había 21.

    No es que una señal sobre y la otra valga: son dos diagnósticos distintos de
    la misma tabla. Lo que sobra es el **recuento** repetido. Aquí se cuentan
    sólo las tablas que ninguna categoría de `table_graph` ha contado ya, y las
    demás siguen visibles en `also_counted_elsewhere` con su diagnóstico —quien
    audite una tabla vacía necesita saber si además tiene un lector huérfano o
    un gemelo léxico, y eso no se pierde—.
    """
    nombres = [str(h["dead"]) for h in hallazgos]
    propias = sorted({n for n in nombres if n not in ya_contadas})
    repetidas = sorted({n for n in nombres if n in ya_contadas})
    evidencia = f"alias_debt.py:{senal} — lector apuntando al gemelo muerto"
    if repetidas:
        evidencia += (
            f"; {len(repetidas)} ya contadas en las categorías de tabla y no se "
            "vuelven a sumar"
        )
    entrada = _entry(propias, evidencia)
    entrada["also_counted_elsewhere"] = repetidas
    return entrada


def _entry(values: list[str], evidence: str) -> dict[str, Any]:
    """Una categoría de deuda: cuánta, unos ejemplos y de dónde salió.

    `items` lleva la lista **completa** además de la muestra. El panel enseña
    `sample` para no volcar cien nombres en pantalla, pero un contador cuyo
    detalle no se puede recuperar no es auditable: al triar los 100 elementos,
    29 quedaban fuera de toda clasificación sólo porque el informe los había
    recortado. La muestra es para leer; la lista completa es para responder.
    """
    ordenados = sorted(values)
    return {
        "count": len(ordenados),
        "sample": ordenados[:SAMPLE],
        "items": ordenados,
        "evidence": evidence,
    }


#: A partir de aquí una copia deja de ser una copia útil. Un día es la cadencia
#: declarada por `triade-backup.timer` (`OnCalendar=daily`); se dan dos de margen
#: para no gritar por un retraso de husos o un reinicio.
BACKUP_MAX_AGE_SECONDS = 2 * 24 * 60 * 60


def _env_file_keys(root: Path) -> set[str]:
    """Nombres de variable definidos en el .env del repo, sin leer sus valores.

    Se devuelven sólo los nombres a propósito: aquí basta con saber si la clave
    está configurada, y el fichero tiene secretos que no deben acabar en un
    informe de deuda.
    """
    env_file = root / ".env"
    try:
        contenido = env_file.read_text(encoding="utf-8")
    except OSError:
        return set()
    nombres: set[str] = set()
    for linea in contenido.splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#") or "=" not in limpia:
            continue
        nombre, _, valor = limpia.partition("=")
        if valor.strip().strip("\"'"):
            nombres.add(nombre.strip())
    return nombres


def _backup_key_configured(root: Path) -> bool:
    """Si el SISTEMA tiene clave de copia, no si la tiene quien está auditando.

    La comprobación miraba `os.getenv` del proceso auditor. Pero quien hace las
    copias es el runtime, y el runtime recibe su configuración del .env del repo
    a través de `EnvironmentFile` de systemd; una shell interactiva no lo tiene
    cargado. El resultado era un fallo fantasma: el 2026-08-10 el proceso de la
    API tenía `TRIADE_BACKUP_KEY_FILE` en su entorno y la auditoría declaraba
    igualmente «sin clave: no se crea ninguna copia».

    Eso es peor que no medir. Esta categoría existe precisamente porque el
    2026-07-31 la clave desapareció de verdad y nadie se enteró en cuatro días;
    si además avisa cuando no pasa nada, deja de creerse cuando pasa.
    """
    if (
        os.getenv("TRIADE_BACKUP_KEY", "").strip()
        or os.getenv("TRIADE_BACKUP_KEY_FILE", "").strip()
    ):
        return True
    return bool({"TRIADE_BACKUP_KEY", "TRIADE_BACKUP_KEY_FILE"} & _env_file_keys(root))


def _backup_protection_gaps(root: Path) -> dict[str, Any]:
    """Lo que impide restaurar: sin clave, sin copia reciente, o sin poder abrirla.

    Es la categoría que faltaba y la que más caro sale no tener. El 2026-07-31 la
    clave desapareció del entorno, el planner dejó de programar backups —su
    condición era exactamente esa variable— y el sistema pasó cuatro días sin una
    sola copia **sin que nada lo dijera**. No había métrica que bajara, ni tabla
    que se quedara vacía: simplemente dejó de ocurrir algo.

    Se miden tres cosas distintas, porque fallan por separado:

    - **sin clave**: no se puede crear ni abrir nada;
    - **copia caducada**: la última es más vieja que la cadencia declarada;
    - **copia sin clave identificada**: el manifiesto no dice qué clave la cifró,
      así que ni sabiendo varias se puede saber cuál la abre.
    """
    gaps: list[str] = []

    tiene_clave = _backup_key_configured(root)
    if not tiene_clave:
        gaps.append(
            "sin TRIADE_BACKUP_KEY ni TRIADE_BACKUP_KEY_FILE: "
            "no se crea ninguna copia y no se abre ninguna existente"
        )
    gaps.extend(_backup_key_file_gaps(root))

    backup_dir = root / "artifacts" / "backups"
    copias = sorted(
        backup_dir.glob("triade-*.db.gz.fernet"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not copias:
        gaps.append("no existe ninguna copia en artifacts/backups")
    else:
        edad = time.time() - copias[0].stat().st_mtime
        if edad > BACKUP_MAX_AGE_SECONDS:
            gaps.append(
                f"la copia más reciente tiene {edad / 86400:.1f} días "
                f"({copias[0].name})"
            )
        sin_huella = [
            copia.name for copia in copias if not _manifest_key_fingerprint(copia)
        ]
        if sin_huella:
            gaps.append(
                f"{len(sin_huella)} copias sin `key_fingerprint` en su manifiesto: "
                "no se puede saber qué clave las abre"
            )
        # Que la copia exista, sea reciente y sepa qué clave la abre no dice
        # todavía que **sirva**. El 2026-08-08 la base se corrompió entre dos
        # copias y la siguiente se archivó igual: la más reciente —la que
        # cualquiera habría elegido para restaurar— era inservible, y ninguna de
        # las tres comprobaciones anteriores lo veía.
        #
        # Sólo se mira la más reciente, y por el manifiesto: descifrar 60 MB en
        # cada medición del panel convertiría el detector en el proceso más caro
        # del sistema. Quien escribe la copia es quien sabe si su origen estaba
        # sano, y ahora lo deja anotado.
        integridad = _manifest_source_integrity(copias[0])
        if integridad != "ok":
            gaps.append(
                f"la copia más reciente ({copias[0].name}) no acredita que su "
                f"origen estuviera íntegro: `source_integrity` = {integridad!r}"
            )

    return {
        "count": len(gaps),
        "sample": gaps[:SAMPLE],
        "evidence": "artifacts/backups/*.json y el entorno de la clave de cifrado",
    }


def _backup_key_file_path(root: Path) -> str:
    """Ruta del fichero de clave, del entorno o —si falta— del .env del repo.

    Sin esto la comprobación de modo de abajo no llegaba a ejecutarse nunca al
    auditar desde una shell: `os.getenv` venía vacío, la función devolvía lista
    vacía y el fallo que se buscaba —la clave en 0744— quedaba sin mirar
    justamente en el sitio donde se mira todo lo demás.
    """
    desde_entorno = os.getenv("TRIADE_BACKUP_KEY_FILE", "").strip()
    if desde_entorno:
        return desde_entorno
    env_file = root / ".env"
    try:
        contenido = env_file.read_text(encoding="utf-8")
    except OSError:
        return ""
    for linea in contenido.splitlines():
        limpia = linea.strip()
        if limpia.startswith("TRIADE_BACKUP_KEY_FILE="):
            return limpia.partition("=")[2].strip().strip("\"'")
    return ""


def _backup_key_file_gaps(root: Path) -> list[str]:
    """La clave declarada, ¿se puede usar de verdad?

    Que la variable exista no significa que la clave sirva. `EncryptedBackup`
    exige `0600` en el fichero y aborta con `PermissionError` si el modo deja
    algo a grupo u otros —correctamente: una clave de backup legible por
    cualquiera no protege nada—. Ese fallo bloquea **crear y restaurar** a la
    vez, y no lo veía nadie: el detector se conformaba con que la variable
    estuviera puesta.

    Encontrado el 2026-08-07 con el fichero en `0744`, al intentar la primera
    restauración real. La rotación del 2026-08-03 lo dejó así y nada lo dijo.
    """
    key_file = _backup_key_file_path(root)
    if not key_file:
        return []
    path = Path(key_file)
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        return [
            (
                f"TRIADE_BACKUP_KEY_FILE apunta a {key_file}, que no se puede "
                "leer: no se crea ninguna copia y no se abre ninguna existente"
            )
        ]
    if mode & 0o077:
        return [
            (
                f"la clave de backup tiene permisos {mode:04o} en vez de 0600: "
                "`EncryptedBackup` la rechaza, así que no se crea ni se restaura"
            )
        ]
    return []


def _manifest_key_fingerprint(backup: Path) -> str | None:
    manifest = backup.with_suffix(backup.suffix + ".json")
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("key_fingerprint")
    except (OSError, ValueError):
        return None


def _manifest_source_integrity(backup: Path) -> str:
    """Qué dijo `integrity_check` del origen cuando se creó esta copia.

    Las copias anteriores al 2026-08-08 no lo llevan, y eso **también** es una
    respuesta: de ellas no consta que su origen estuviera sano, que es
    exactamente lo que hay que saber antes de confiar en una.
    """
    manifest = backup.with_suffix(backup.suffix + ".json")
    try:
        valor = json.loads(manifest.read_text(encoding="utf-8")).get("source_integrity")
    except (OSError, ValueError):
        return "sin manifiesto legible"
    return str(valor) if valor else "no consta"


def _declared_services_not_running(
    root: Path, db_path: Path | None = None
) -> dict[str, Any]:
    """Unidades de `deploy/systemd/` sin un proceso vivo que las cumpla.

    Es la categoría que faltaba, y faltaba justo donde más duele: el watchdog y
    el backup están declarados como servicios, el grafo los ve, su código está
    inervado —`triade/runtime/watchdog.py` lo importan 5 módulos— y **nadie los
    arranca**. En el entrypoint_graph salían como `legacy`, un estado que se
    inventó para no llamar deuda a 45 utilidades manuales, y que de paso los
    escondió.

    Una utilidad que se ejecuta a mano y un órgano de vigilancia parado no se
    distinguen por si alguien los citó en un `.md`: se distinguen por si algo
    declaró que debían estar corriendo. Un fichero `.service` es esa
    declaración.

    La evidencia es el process table, no el repositorio: «detenido» sólo se
    puede medir en vivo. Sin `/proc` legible, devuelve `NEEDS_EVIDENCE` en lugar
    de afirmar que todo está bien.
    """
    unit_dir = root / "deploy" / "systemd"
    if not unit_dir.is_dir():
        return {
            "count": 0,
            "sample": [],
            "evidence": "sin deploy/systemd: NEEDS_EVIDENCE",
        }

    declared: list[tuple[str, str]] = []
    for unit in sorted(unit_dir.glob("*.service")):
        for line in unit.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("ExecStart="):
                declared.append((unit.name, line.split("=", 1)[1].strip()))
                break

    running = _running_commands()
    if running is None:
        return {
            "count": 0,
            "sample": [],
            "evidence": "process table ilegible: NEEDS_EVIDENCE",
        }

    stopped: list[str] = []
    for unit_name, exec_start in declared:
        # Se compara por el argumento distintivo —el script o el módulo—, no por
        # la ruta del intérprete: el runtime real corre bajo `nohup` con otro
        # binario de Python y compararlo entero daría todo por parado.
        marker = next(
            (
                part
                for part in reversed(exec_start.split())
                if part.endswith(".py") or ":" in part or part == "serve"
            ),
            exec_start,
        )
        if any(marker in cmd for cmd in running):
            continue
        # No hay proceso con ese nombre, pero la pregunta que importa no es
        # «¿corre este proceso?» sino «¿ocurre esta función?». El watchdog, los
        # workers y el backup se cumplen aquí como hilo o como tarea del proceso
        # de la API, no como el servicio declarado: exigir el proceso marcaría
        # como parado algo que está pasando. Se mira el efecto, que es la misma
        # regla que rige el resto del grafo: evidencia antes que declaración.
        efecto = _service_effect_evidence(marker, root, db_path)
        if efecto is None:
            stopped.append(f"{unit_name} → {marker}: sin proceso y sin efecto reciente")

    return {
        "count": len(stopped),
        "sample": sorted(stopped)[:SAMPLE],
        "evidence": (
            "deploy/systemd/*.service frente a /proc/*/cmdline y al efecto "
            "reciente de cada servicio"
        ),
    }


#: Cuánto puede tardar el efecto de un servicio antes de contar como ausente.
#: Generoso a propósito: se busca «esto no está ocurriendo», no un retraso.
SERVICE_EFFECT_MAX_AGE_SECONDS = 3 * 60 * 60


def _service_effect_evidence(
    marker: str, root: Path, db_path: Path | None
) -> str | None:
    """Prueba viva de que la función del servicio ocurrió hace poco, o `None`.

    Cada servicio deja una huella distinta y hay que buscarla donde cae, no
    donde sería cómodo: el watchdog en sus instantáneas de salud, los workers en
    las tareas que cierran, el backup en el fichero que produce.
    """
    # Las consultas van literales y no por parámetro a propósito: el grafo extrae
    # las tablas de los literales del AST, así que un nombre de tabla en variable
    # es una lectura que existe y que el grafo no puede ver. Escribirlas así es lo
    # que hace que `runtime_health_snapshots` deje de figurar como escrita y nunca
    # leída: ahora tiene un lector, y el grafo lo demuestra.
    if "watchdog" in marker:
        return _recent_row(
            db_path, "SELECT MAX(created_at) FROM runtime_health_snapshots"
        )
    if "workers" in marker:
        return _recent_row(db_path, "SELECT MAX(updated_at) FROM autonomous_tasks")
    if "backup" in marker:
        copias = sorted(
            (root / "artifacts" / "backups").glob("triade-*.db.gz.fernet"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if copias and time.time() - copias[0].stat().st_mtime < BACKUP_MAX_AGE_SECONDS:
            return copias[0].name
        return None
    return None


def _recent_row(db_path: Path | None, query: str) -> str | None:
    """Devuelve el instante de la última fila si es reciente, o `None`.

    Recibe la consulta ya escrita, nunca el nombre de la tabla: así el literal
    queda en el AST y el grafo puede contar esta lectura.
    """
    if db_path is None:
        return None
    connection = open_readonly(db_path)
    if connection is None:
        return None
    try:
        row = connection.execute(query).fetchone()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    if not row or not row[0]:
        return None
    stamp = str(row[0]).replace("Z", "+00:00").replace(" ", "T")
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    edad = (datetime.now(UTC) - moment).total_seconds()
    return str(row[0]) if edad < SERVICE_EFFECT_MAX_AGE_SECONDS else None


def _running_commands() -> list[str] | None:
    """Líneas de comando vivas, o `None` si no se pueden leer."""
    proc = Path("/proc")
    if not proc.is_dir():
        return None
    commands: list[str] = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if raw:
            commands.append(raw.replace(b"\x00", b" ").decode("utf-8", "replace"))
    return commands


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
            # Un eslabón bajo demanda ocioso no es un corte: `plan` sólo escribe
            # cuando alguien pide una capacidad, y una conversación normal
            # resuelve `conversation` y no debe crear goal. Sin filas **nunca**
            # sí se sigue contando arriba, porque entonces no hay prueba de que
            # el eslabón haya funcionado jamás.
            if stage in ON_DEMAND_STAGES:
                continue
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

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
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    alias = build_alias_debt(
        root, table_profiles=profiles_from_artifact(_load(cache_dir, "table_graph"))
    )
    # `suspected_dead_status` entra igual que los demás: rebajar la confianza de
    # un hallazgo no es motivo para esconderlo del contador.
    for senal in (
        "orphan_reader",
        "lexical_alias",
        "dead_status_value",
        "suspected_dead_status",
    ):
        hallazgos = [h for h in alias["findings"] if h["signal"] == senal]
        items[f"alias_debt_{senal}"] = _entry(
            [h["dead"] for h in hallazgos],
            f"alias_debt.py:{senal} — lector apuntando al gemelo muerto",
        )
    items["declared_services_not_running"] = _declared_services_not_running(
        root, db_path
    )
    items["backup_protection_gaps"] = _backup_protection_gaps(root)

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

    tiene_clave = bool(
        os.getenv("TRIADE_BACKUP_KEY", "").strip()
        or os.getenv("TRIADE_BACKUP_KEY_FILE", "").strip()
    )
    if not tiene_clave:
        gaps.append(
            "sin TRIADE_BACKUP_KEY ni TRIADE_BACKUP_KEY_FILE: "
            "no se crea ninguna copia y no se abre ninguna existente"
        )
    gaps.extend(_backup_key_file_gaps())

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

    return {
        "count": len(gaps),
        "sample": gaps[:SAMPLE],
        "evidence": "artifacts/backups/*.json y el entorno de la clave de cifrado",
    }


def _backup_key_file_gaps() -> list[str]:
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
    key_file = os.getenv("TRIADE_BACKUP_KEY_FILE", "").strip()
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

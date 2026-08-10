#!/usr/bin/env python3
"""Aplica las migraciones de retirada que nadie ejecuta.

Tríade no tiene un aplicador central de migraciones: cada módulo ejecuta la suya
con `conn.executescript()` cuando la necesita —`ResourceLedger` corre la 009 y la
018, el metabolismo la 032, y así—. Ese reparto funciona para las migraciones
aditivas, porque cada una tiene un dueño que la necesita. Las de retirada no
tienen dueño: nadie necesita que una tabla desaparezca, así que `034`, `035` y
`036` llevan escritas, documentadas y probadas desde hace semanas sin haberse
ejecutado nunca contra ninguna base, ni siquiera una nueva.

El resultado medido el 2026-08-10: diez de las treinta y una deudas reales que
reporta `/api/internal-graphs/debt` son tablas cuya retirada ya estaba decidida
y escrita. No son deuda de análisis —el trabajo de decidir ya se hizo— sino una
operación pendiente sin ruta que la ejecute.

Esto es esa ruta, y es deliberadamente conservadora:

- `dry-run` por defecto. Sin `--apply` no toca nada.
- Se niega a borrar una tabla que tenga filas, aunque la migración lo pida. Una
  tabla con datos no es huérfana: es un hallazgo, y lo dice en vez de borrarla.
- Copia de seguridad antes de tocar, con la ruta en el manifiesto.
- Manifiesto de lo hecho, con el esquema de cada tabla retirada, para que la
  decisión sea auditable después.

Algunas migraciones avisan en su cabecera de que retirar esas tablas exige
rebasar el ancla de identidad con `IdentityContinuity.migrate_anchor()`; sin eso
el runtime arranca en `degraded_safe_identity_mismatch`. Ese requisito se lee de
cada fichero y sólo entra con `--include-anchor-rebase`, que es una decisión del
operador y no de este script.

Se lee y no se lista a mano porque la lista escrita a mano estaba mal: marcaba
una sola de las dos migraciones que lo declaran. Que no causara daño fue suerte
—el manifiesto de identidad ya iba por `schema_version: 036`, así que el ancla
cubría de antemano las tres retiradas y sólo faltaba ejecutar el `DROP`—, pero
una lista paralela a lo que dice el fichero se desincroniza por definición.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO / "triade/memory/triade.db"
MIGRATIONS = REPO / "triade/memory/migrations"
MANIFEST_DIR = REPO / "artifacts/migrations"

_DROP = re.compile(
    r"DROP\s+TABLE\s+IF\s+EXISTS\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE
)

#: Una migración declara por sí misma que exige rebasar el ancla de identidad.
_ANCHOR_MARK = "migrate_anchor"


def _statements(sql: str) -> list[str]:
    sin_comentarios = "\n".join(
        linea for linea in sql.splitlines() if not linea.strip().startswith("--")
    )
    return [s.strip() for s in sin_comentarios.split(";") if s.strip()]


def retirement_migrations() -> list[Path]:
    """Migraciones cuyo único efecto es retirar esquema, descubiertas al vuelo.

    Estaban escritas a mano en una tupla, y eso tenía un coste que sólo apareció
    al correr la suite: el nombre de una migración de retirada contiene el nombre
    de la tabla que retira, así que escribirlo aquí mete ese nombre en código
    productivo. Hay un guardián que vigila exactamente eso
    —`test_el_contrato_retirado_no_tiene_lector_en_produccion`— y tiene razón: un
    lector de una tabla que nadie puede llenar siempre recibe el caso vacío, y
    desde fuera no se distingue de una consulta de verdad.

    Descubrirlas es además mejor de por sí. Una migración de retirada nueva entra
    sola, sin que nadie tenga que acordarse de añadirla aquí, que es justo el
    olvido que dejó `034`, `035` y `036` sin ejecutar durante semanas.

    El criterio es estructural, no de nombre: todas sus sentencias son
    `DROP TABLE`. `019_legacy_retirement.sql` se llama «retirement» y crea
    tablas, así que queda fuera por lo que hace y no por cómo se llama.
    """
    encontradas = []
    for ruta in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")):
        sentencias = _statements(ruta.read_text(encoding="utf-8"))
        if sentencias and all(s.upper().startswith("DROP TABLE") for s in sentencias):
            encontradas.append(ruta)
    return encontradas


def requires_anchor_rebase(path: Path) -> bool:
    """La migración lo dice en su propia cabecera, no una lista aparte."""
    return _ANCHOR_MARK in path.read_text(encoding="utf-8")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _tables_dropped_by(path: Path) -> list[str]:
    return _DROP.findall(path.read_text(encoding="utf-8"))


def _row_count(conn: sqlite3.Connection, table: str) -> int | None:
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM '{table}'").fetchone()[0])
    except sqlite3.Error:
        return None


def _schema_of(conn: sqlite3.Connection, table: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def plan(db_path: Path, *, include_anchor_rebase: bool) -> dict[str, Any]:
    """Qué haría, sin hacerlo. Es también lo que se imprime en `dry-run`."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        migraciones: list[dict[str, Any]] = []
        for ruta in retirement_migrations():
            nombre = ruta.name
            necesita_ancla = requires_anchor_rebase(ruta)
            tablas = []
            for tabla in _tables_dropped_by(ruta):
                filas = _row_count(conn, tabla)
                tablas.append(
                    {
                        "table": tabla,
                        "present": filas is not None,
                        "rows": filas,
                        # Una tabla con filas no se toca: que tenga datos
                        # contradice la premisa de la migración y eso hay que
                        # mirarlo, no ejecutarlo.
                        "action": (
                            "absent"
                            if filas is None
                            else "drop"
                            if filas == 0
                            else "refuse_has_rows"
                        ),
                        "schema": _schema_of(conn, tabla),
                    }
                )
            bloqueada = necesita_ancla and not include_anchor_rebase
            migraciones.append(
                {
                    "migration": nombre,
                    "requires_anchor_rebase": necesita_ancla,
                    "blocked": "requires --include-anchor-rebase"
                    if bloqueada
                    else None,
                    "tables": tablas,
                }
            )
    finally:
        conn.close()

    a_borrar = [
        t["table"]
        for m in migraciones
        if not m.get("blocked") and not m.get("skipped")
        for t in m.get("tables", [])
        if t["action"] == "drop"
    ]
    con_filas = [
        {"table": t["table"], "rows": t["rows"]}
        for m in migraciones
        for t in m.get("tables", [])
        if t["action"] == "refuse_has_rows"
    ]
    return {
        "generated_at": _now(),
        "db_path": str(db_path),
        "migrations": migraciones,
        "would_drop": a_borrar,
        "refused_with_rows": con_filas,
    }


def _backup(db_path: Path) -> str:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    destino = MANIFEST_DIR / f"pre-retirement-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.db"
    origen = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    copia = sqlite3.connect(destino)
    try:
        origen.backup(copia)
    finally:
        copia.close()
        origen.close()
    return str(destino)


def apply(db_path: Path, *, include_anchor_rebase: bool) -> dict[str, Any]:
    previsto = plan(db_path, include_anchor_rebase=include_anchor_rebase)
    if not previsto["would_drop"]:
        return {**previsto, "applied": False, "reason": "nothing_to_drop"}

    respaldo = _backup(db_path)
    conn = sqlite3.connect(db_path, timeout=30)
    retiradas: list[str] = []
    try:
        with conn:
            for tabla in previsto["would_drop"]:
                # Se relee el recuento dentro de la transacción: entre el plan y
                # aquí el organismo sigue vivo y pudo escribir.
                filas = _row_count(conn, tabla)
                if filas != 0:
                    continue
                conn.execute(f"DROP TABLE IF EXISTS '{tabla}'")
                retiradas.append(tabla)
    finally:
        conn.close()

    manifiesto = {
        **previsto,
        "applied": True,
        "backup": respaldo,
        "dropped": retiradas,
        "applied_at": _now(),
    }
    destino = MANIFEST_DIR / f"retirement-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    destino.write_text(
        json.dumps(manifiesto, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    manifiesto["manifest"] = str(destino)
    return manifiesto


def rollback(manifest_path: Path, db_path: Path | None = None) -> dict[str, Any]:
    """Deshace una retirada concreta a partir de su manifiesto.

    Se puede porque el manifiesto guarda el `CREATE TABLE` de cada tabla y
    porque sólo se retiran tablas vacías: restaurar es recrear el esquema, no
    recuperar datos. Si alguna volvió a existir entretanto se deja como está y
    se dice —recrearla encima sería peor que no hacer nada.

    Existir importa más que usarse: una operación destructiva sin vuelta atrás
    no debería haberse ofrecido, y sin este camino el detector de deuda tenía
    razón al no reconocer este script como herramienta reversible.
    """
    manifiesto = json.loads(manifest_path.read_text(encoding="utf-8"))
    objetivo = Path(db_path or manifiesto["db_path"])
    esquemas = {
        t["table"]: t.get("schema")
        for m in manifiesto.get("migrations", [])
        for t in m.get("tables", [])
    }

    conn = sqlite3.connect(objetivo, timeout=30)
    restauradas: list[str] = []
    omitidas: list[dict[str, str]] = []
    try:
        with conn:
            for tabla in manifiesto.get("dropped", []):
                esquema = esquemas.get(tabla)
                if not esquema:
                    omitidas.append(
                        {"table": tabla, "reason": "schema_not_in_manifest"}
                    )
                    continue
                existe = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (tabla,),
                ).fetchone()
                if existe:
                    omitidas.append({"table": tabla, "reason": "already_present"})
                    continue
                conn.execute(esquema)
                restauradas.append(tabla)
    finally:
        conn.close()

    return {
        "rolled_back": True,
        "manifest": str(manifest_path),
        "db_path": str(objetivo),
        "restored": restauradas,
        "skipped": omitidas,
        "at": _now(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--apply", action="store_true", help="ejecuta; sin esto sólo informa"
    )
    parser.add_argument(
        "--rollback",
        type=Path,
        metavar="MANIFIESTO",
        help="recrea las tablas retiradas por ese manifiesto",
    )
    parser.add_argument(
        "--include-anchor-rebase",
        action="store_true",
        help="incluye las migraciones que exigen rebasar el ancla de identidad",
    )
    args = parser.parse_args()

    if args.rollback:
        resultado = rollback(args.rollback, args.db if args.db != DEFAULT_DB else None)
    elif args.apply:
        resultado = apply(args.db, include_anchor_rebase=args.include_anchor_rebase)
    else:
        resultado = plan(args.db, include_anchor_rebase=args.include_anchor_rebase)
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

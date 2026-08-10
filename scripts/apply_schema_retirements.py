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

`036_retire_goals.sql` avisa de que retirar `goals` exige rebasar el ancla de
identidad con `IdentityContinuity.migrate_anchor()`; sin eso el runtime arranca
en `degraded_safe_identity_mismatch`. Por eso las migraciones que lo requieren
van marcadas y sólo entran con `--include-anchor-rebase`, que es una decisión
del operador y no de este script.
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

#: Migraciones cuyo único efecto es retirar esquema huérfano.
RETIREMENT_MIGRATIONS = (
    "034_retire_orphan_schema.sql",
    "035_retire_neuron_certifications.sql",
    "036_retire_goals.sql",
)

#: Las que además exigen una operación gobernada sobre la identidad.
REQUIRES_ANCHOR_REBASE = frozenset({"036_retire_goals.sql"})

_DROP = re.compile(
    r"DROP\s+TABLE\s+IF\s+EXISTS\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE
)


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
        for nombre in RETIREMENT_MIGRATIONS:
            ruta = MIGRATIONS / nombre
            if not ruta.exists():
                migraciones.append(
                    {"migration": nombre, "skipped": "migration_file_missing"}
                )
                continue
            necesita_ancla = nombre in REQUIRES_ANCHOR_REBASE
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--apply", action="store_true", help="ejecuta; sin esto sólo informa"
    )
    parser.add_argument(
        "--include-anchor-rebase",
        action="store_true",
        help="incluye las migraciones que exigen rebasar el ancla de identidad",
    )
    args = parser.parse_args()

    resultado = (
        apply(args.db, include_anchor_rebase=args.include_anchor_rebase)
        if args.apply
        else plan(args.db, include_anchor_rebase=args.include_anchor_rebase)
    )
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

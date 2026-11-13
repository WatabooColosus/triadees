"""Reconstruye la fila `runs` de los ciclos autónomos que nunca la escribieron.

`model_events.run_id` referencia `runs(run_id)`, pero hasta el 2026-08-09 el
ciclo del supervisor escribía un evento por vuelta sin crear nunca su fila
padre. Quedaron 4.073 eventos huérfanos repartidos en 719 ciclos. El escritor ya
está corregido; esto repara lo que se acumuló antes.

No se inventa nada: cada campo sale de los propios eventos del ciclo.

    run_id      el que ya traen los eventos
    source      'runtime', como las filas que escribe el supervisor corregido
    created_at  MIN(model_events.created_at) del ciclo
    closed_at   MAX(model_events.created_at) del ciclo
    user_input  frase fija que dice qué es y que fue reconstruida

Lo único que no se deriva es `user_input`, que es NOT NULL y en un ciclo
autónomo no existe por definición: nadie escribió nada. Se pone una frase que lo
dice en voz alta y que además hace el backfill reversible de un solo DELETE.

Por defecto no escribe. Hay que pasar --apply.

    python scripts/backfill_runtime_runs.py            # muestra qué haría
    python scripts/backfill_runtime_runs.py --apply    # lo hace
    python scripts/backfill_runtime_runs.py --revertir  # deshace
"""

from __future__ import annotations

import argparse
import sqlite3
import sys

MARCA = "(fila reconstruida por backfill_runtime_runs)"
DESCRIPCION = (
    "ciclo autónomo del supervisor: comprobación de modelo sin petición humana " + MARCA
)

SELECCION = """
    SELECT m.run_id, MIN(m.created_at) AS primero, MAX(m.created_at) AS ultimo,
           COUNT(*) AS eventos
    FROM model_events m
    WHERE NOT EXISTS (SELECT 1 FROM runs r WHERE r.run_id = m.run_id)
    GROUP BY m.run_id
"""


def analizar(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(SELECCION).fetchall()


def huerfanas(conn: sqlite3.Connection) -> int:
    return len(conn.execute("PRAGMA foreign_key_check").fetchall())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="triade/memory/triade.db")
    parser.add_argument("--apply", action="store_true", help="escribe de verdad")
    parser.add_argument(
        "--revertir", action="store_true", help="borra las filas reconstruidas"
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db, timeout=30)
    conn.row_factory = sqlite3.Row

    if args.revertir:
        with conn:
            borradas = conn.execute(
                "DELETE FROM runs WHERE source='runtime' AND user_input LIKE ?",
                (f"%{MARCA}%",),
            ).rowcount
        print(f"revertidas {borradas} filas reconstruidas")
        print(f"huérfanas ahora: {huerfanas(conn)}")
        return 0

    filas = analizar(conn)
    total_eventos = sum(f["eventos"] for f in filas)
    print(f"ciclos sin fila padre : {len(filas)}")
    print(f"eventos que rescatan  : {total_eventos}")
    if filas:
        print(f"rango                 : {filas[0]['primero'][:10]} .. ", end="")
        print(max(f["ultimo"] for f in filas)[:10])
    print(f"huérfanas antes       : {huerfanas(conn)}")

    if not args.apply:
        print("\n(dry-run: no se ha escrito nada; pasa --apply)")
        return 0

    # `BEGIN IMMEDIATE` toma el lock de escritura desde el principio: con el
    # runtime vivo escribiendo en la misma base, empezar en modo diferido
    # arriesga un `database is locked` a mitad del INSERT.
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.executemany(
            """INSERT INTO runs (run_id, source, user_input, status, created_at, closed_at)
            VALUES (?, 'runtime', ?, 'completed', ?, ?)""",
            [(f["run_id"], DESCRIPCION, f["primero"], f["ultimo"]) for f in filas],
        )
        restantes = conn.execute(
            "SELECT COUNT(*) FROM model_events m "
            "WHERE NOT EXISTS (SELECT 1 FROM runs r WHERE r.run_id = m.run_id)"
        ).fetchone()[0]
        if restantes:
            conn.rollback()
            print(f"ABORTADO: quedaban {restantes} eventos sin padre", file=sys.stderr)
            return 1
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        print(f"ABORTADO por error de base: {exc}", file=sys.stderr)
        return 1

    print(f"\ninsertadas {len(filas)} filas")
    print(f"huérfanas después     : {huerfanas(conn)}")
    print(f"quick_check           : {conn.execute('PRAGMA quick_check').fetchone()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

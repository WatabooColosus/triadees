#!/usr/bin/env python3
"""Observa el ciclo de educación neuronal sin tocarlo.

Sólo lee. No crea sesiones, no fuerza el `_target()`, no siembra actividad: si
esta herramienta empujara el ciclo, lo que registrara dejaría de ser una
observación y pasaría a ser un montaje.

Registra cada transición de las seis etapas del recorrido en un JSONL:

    lesson_prepared → aplicaciones medibles → baseline → post_score
    → decisión → conservación o rollback

Uso:
    python scripts/observe_neuron_education.py --minutos 120 --cada 300
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CAMPOS = (
    "session_id",
    "neuron_id",
    "state",
    "result",
    "baseline_score",
    "post_score",
    "applied_run_count",
    "regression_count",
    "rollback_ref",
    "created_at",
    "finished_at",
)


def _ahora() -> str:
    return datetime.now(UTC).isoformat()


def _muestra(db: Path) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        sesiones = {
            str(r["session_id"]): dict(r)
            for r in conn.execute(
                f"SELECT {','.join(CAMPOS)} FROM neuron_education_sessions"
            )
        }
        aplicaciones = {
            str(r["session_id"]): int(r["n"])
            for r in conn.execute(
                "SELECT session_id, COUNT(*) n FROM neuron_education_applications "
                "GROUP BY session_id"
            )
        }
        eventos = int(
            conn.execute("SELECT COUNT(*) FROM neuron_education_events").fetchone()[0]
        )
    finally:
        conn.close()
    for sid, fila in sesiones.items():
        fila["applications_rows"] = aplicaciones.get(sid, 0)
    return {"sesiones": sesiones, "eventos": eventos}


def _diferencias(antes: dict[str, Any], ahora: dict[str, Any]) -> list[dict[str, Any]]:
    cambios: list[dict[str, Any]] = []
    viejas = antes["sesiones"]
    for sid, fila in ahora["sesiones"].items():
        previa = viejas.get(sid)
        if previa is None:
            cambios.append({"tipo": "sesion_nueva", "sesion": fila})
            continue
        campos = {
            k: {"antes": previa.get(k), "ahora": v}
            for k, v in fila.items()
            if previa.get(k) != v
        }
        if campos:
            cambios.append(
                {
                    "tipo": "sesion_avanza",
                    "session_id": sid,
                    "neuron_id": fila["neuron_id"],
                    "campos": campos,
                }
            )
    if ahora["eventos"] != antes["eventos"]:
        cambios.append(
            {
                "tipo": "eventos",
                "antes": antes["eventos"],
                "ahora": ahora["eventos"],
            }
        )
    return cambios


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="triade/memory/triade.db")
    p.add_argument("--minutos", type=float, default=120.0)
    p.add_argument("--cada", type=float, default=300.0)
    p.add_argument("--salida", default="logs/observacion-educacion-neuronal.jsonl")
    args = p.parse_args()

    db = Path(args.db)
    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)

    estado = _muestra(db)
    with salida.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "ts": _ahora(),
                    "tipo": "inicio",
                    "sesiones": len(estado["sesiones"]),
                    "eventos": estado["eventos"],
                    "estados": sorted(
                        {str(s["state"]) for s in estado["sesiones"].values()}
                    ),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        fh.flush()

        limite = time.monotonic() + args.minutos * 60
        while time.monotonic() < limite:
            time.sleep(args.cada)
            try:
                nuevo = _muestra(db)
            except sqlite3.Error as exc:
                fh.write(
                    json.dumps(
                        {"ts": _ahora(), "tipo": "error_lectura", "detalle": str(exc)},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                fh.flush()
                continue
            for cambio in _diferencias(estado, nuevo):
                fh.write(
                    json.dumps({"ts": _ahora(), **cambio}, ensure_ascii=False) + "\n"
                )
            fh.flush()
            estado = nuevo

        fh.write(json.dumps({"ts": _ahora(), "tipo": "fin"}, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

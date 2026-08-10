#!/usr/bin/env python3
"""Clasifica las tareas en `dead_letter` y vigila que no nazcan nuevas.

Una cola de muertos que sólo se cuenta no dice nada: 181 puede ser una hemorragia
abierta o la cicatriz de una que ya se cerró, y el número es el mismo. Lo que
distingue una cosa de la otra es cuándo murió la última y si el tipo que sangraba
vuelve a completar hoy.

Cada dead letter se clasifica por su causa raíz y, sobre todo, por si reintentarla
tendría algún valor:

- `superseded_periodic` — tarea periódica cuyo trabajo ya hizo una instancia
  posterior que sí completó. Reintentar una de 2026-08-09 no recupera nada: sería
  fabricar ejecuciones.
- `uncertain_quarantined` — el runtime no pudo demostrar que se completara y la
  cerró a propósito. La gobernanza funcionando, no un fallo.
- `handler_unverifiable` — el handler afirmó un efecto sin recibo verificable y
  se le negó. Igual: gobernanza.
- `environment` — faltaba algo del entorno (clave de backup, binario en PATH).
  Reparable arreglando el entorno, no reintentando la fila.
- `state_race` — el planner leyó un estado y el handler encontró otro. Bug real
  si sigue ocurriendo; histórico si no.
- `active_bug` — la causa sigue produciendo muertes en las últimas 24 h. Es la
  única categoría que exige trabajo de ingeniería ahora.

No borra nada. La cola de muertos es el registro de lo que salió mal y borrarla
es perder la única prueba de que ocurrió.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO / "triade/memory/triade.db"
ARTIFACTS = REPO / "artifacts/dead_letters"

#: Tipos que el planner reencola por su cuenta: una instancia perdida la sustituye
#: la siguiente, así que reintentar la muerta no recupera trabajo.
PERIODIC_TYPES = frozenset(
    {
        "pulse_check",
        "encrypted_backup",
        "system_debt_scan",
        "learning_evidence_generation",
        "neuron_education_cycle",
        "bodega_global_review",
        "research_curriculum",
        "pending_learning_review",
    }
)

_CAUSES: tuple[tuple[str, str], ...] = (
    ("expired_lease_attempts_exhausted", "lease_expired"),
    ("dispatch_livelock_guard", "livelock_guard"),
    ("no_backup_key_configured", "environment"),
    ("no encontrado en PATH", "environment"),
    ("timeout:task_timeout", "timeout"),
    ("afirmó un efecto sin recibo verificable", "handler_unverifiable"),
    ("unknown_handler_status", "handler_unverifiable"),
    ("Solo se verifica un candidato", "state_race"),
    ("Solo se evalúa un candidato", "state_race"),
    ("uncertain_without_artifact", "uncertain_quarantined"),
)


def _cause(last_error: str | None) -> str:
    texto = str(last_error or "")
    for aguja, nombre in _CAUSES:
        if aguja in texto:
            return nombre
    return "unclassified" if texto else "no_error_recorded"


def _normalized_error(last_error: str | None) -> str:
    texto = str(last_error or "NULL")
    texto = re.sub(r"[0-9a-f]{8,}", "<id>", texto)
    return re.sub(r"\d+", "<n>", texto)[:120]


def triage(db_path: Path, *, window_hours: int = 24) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        muertas = list(
            conn.execute(
                "SELECT task_id, task_type, status, attempt, max_attempts,"
                " created_at, updated_at, last_error FROM autonomous_tasks"
                " WHERE status = 'dead_letter' ORDER BY updated_at"
            )
        )
        # Un tipo que vuelve a completar después de su última muerte demuestra
        # que la causa dejó de morder: es la diferencia entre cicatriz y herida.
        ultimo_exito = {
            str(r["task_type"]): str(r["last_ok"])
            for r in conn.execute(
                "SELECT task_type, MAX(updated_at) AS last_ok FROM autonomous_tasks"
                " WHERE status IN ('completed','observed') GROUP BY task_type"
            )
        }
    finally:
        conn.close()

    corte = (datetime.now(UTC) - timedelta(hours=window_hours)).isoformat()
    items: list[dict[str, Any]] = []
    for fila in muertas:
        tipo = str(fila["task_type"])
        causa = _cause(fila["last_error"])
        murio = str(fila["updated_at"] or "")
        reciente = murio >= corte
        exito_posterior = ultimo_exito.get(tipo, "") > murio

        # El orden importa y costó una lectura equivocada: clasificar por
        # recencia primero marcaba 92 muertes como bug vigente sólo porque la
        # hemorragia se cerró hace siete horas y la ventana era de veinticuatro.
        # «Murió hace poco» y «la causa sigue mordiendo» son cosas distintas, y
        # la segunda es la que exige trabajo. Que el tipo haya vuelto a completar
        # después de esa muerte es la prueba de que dejó de morder.
        if exito_posterior:
            clasificacion, reintentable = (
                causa
                if causa in {"uncertain_quarantined", "handler_unverifiable"}
                else "environment"
                if causa == "environment"
                else "superseded_periodic"
                if tipo in PERIODIC_TYPES
                else "recovered_type",
                False,
            )
        elif reciente:
            clasificacion, reintentable = "active_bug", True
        elif causa in {"uncertain_quarantined", "handler_unverifiable"}:
            clasificacion, reintentable = causa, False
        elif causa == "environment":
            clasificacion, reintentable = "environment", False
        elif tipo in PERIODIC_TYPES and exito_posterior:
            clasificacion, reintentable = "superseded_periodic", False
        elif causa == "state_race":
            clasificacion, reintentable = "state_race", False
        else:
            clasificacion, reintentable = "unresolved_legacy", False

        items.append(
            {
                "task_id": str(fila["task_id"]),
                "task_type": tipo,
                "cause": causa,
                "classification": clasificacion,
                "retryable": reintentable,
                "attempt": f"{fila['attempt']}/{fila['max_attempts']}",
                "created_at": str(fila["created_at"]),
                "died_at": murio,
                "error": _normalized_error(fila["last_error"]),
                "type_succeeded_after_death": exito_posterior,
            }
        )

    nuevas = [i for i in items if i["classification"] == "active_bug"]
    ultima = max((i["died_at"] for i in items), default=None)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "db_path": str(db_path),
        "total": len(items),
        "window_hours": window_hours,
        "new_dead_letters_in_window": len(nuevas),
        "last_death_at": ultima,
        "by_classification": dict(Counter(i["classification"] for i in items)),
        "by_cause": dict(Counter(i["cause"] for i in items)),
        "by_task_type": dict(Counter(i["task_type"] for i in items)),
        "retryable_total": sum(1 for i in items if i["retryable"]),
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--window-hours", type=int, default=24)
    parser.add_argument("--write", action="store_true", help="guarda el artefacto")
    args = parser.parse_args()

    informe = triage(args.db, window_hours=args.window_hours)
    resumen = {k: v for k, v in informe.items() if k != "items"}
    print(json.dumps(resumen, indent=2, ensure_ascii=False))

    if args.write:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        destino = ARTIFACTS / f"dead-letters-{datetime.now(UTC):%Y%m%d}.json"
        destino.write_text(
            json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nartefacto: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

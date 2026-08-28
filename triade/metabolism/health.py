from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triade.db import sqlite3
from triade.runtime.task_status import ELIGIBLE, sql_placeholders


class HealthSensors:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def inspect(self) -> dict[str, Any]:
        sensors: dict[str, Any] = {
            "checked_at": datetime.now(UTC).isoformat(),
            "db": self._check_db(),
            "disk": self._check_disk(),
            "memory": self._check_memory(),
            "heartbeat": self._check_heartbeat(),
            "leases": self._check_leases(),
            "queue": self._check_queue(),
            "vital_chain": self._check_vital_chain(),
        }
        healthy = all(
            s.get("ok", False) for s in sensors.values() if isinstance(s, dict)
        )
        sensors["healthy"] = healthy
        return sensors

    def _check_db(self) -> dict[str, Any]:
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                quick = str(conn.execute("PRAGMA quick_check").fetchone()[0])
                tables = {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                return {
                    "ok": quick == "ok",
                    "quick_check": quick,
                    "table_count": len(tables),
                }
        except (sqlite3.Error, OSError) as exc:
            return {"ok": False, "error": type(exc).__name__}

    def _check_disk(self) -> dict[str, Any]:
        try:
            import shutil

            usage = shutil.disk_usage(self.db_path.parent)
            free_gb = usage.free / (1024**3)
            return {
                "ok": free_gb > 2.0,
                "free_gb": round(free_gb, 1),
                "total_gb": round(usage.total / (1024**3), 1),
            }
        except OSError:
            return {"ok": False, "error": "disk_check_failed"}

    def _check_memory(self) -> dict[str, Any]:
        try:
            import psutil  # type: ignore[import-untyped]

            mem = psutil.virtual_memory()
            avail_gb = mem.available / (1024**3)
            return {
                "ok": avail_gb > 1.0,
                "available_gb": round(avail_gb, 1),
                "percent": mem.percent,
            }
        except (ImportError, OSError):
            return {"ok": False, "error": "memory_check_failed"}

    def _check_heartbeat(self) -> dict[str, Any]:
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                row = conn.execute(
                    "SELECT updated_at FROM live_runtime_heartbeat ORDER BY updated_at DESC LIMIT 1"
                ).fetchone()
                if row is None:
                    return {"ok": False, "error": "no_heartbeat_found"}
                ts = datetime.fromisoformat(row[0])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                age = (datetime.now(UTC) - ts).total_seconds()
                return {
                    "ok": age < 180,
                    "age_seconds": int(age),
                }
        except (sqlite3.Error, OSError, ValueError) as exc:
            return {"ok": False, "error": type(exc).__name__}

    def _check_leases(self) -> dict[str, Any]:
        """Leases vencidos en la cola viva.

        Vigilaba `worker_tasks.status='claimed'`: la cola legacy, sin una sola
        fila `claimed` en toda su historia y sin escrituras desde 2026-07-29. El
        sensor daba `ok` siempre, así que `lease_supervision` no nacía nunca y
        `AutonomousTaskStore.recover_expired()` no llegaba a llamarse en
        producción. Se encontró con dos tareas atascadas 12 y 6 minutos con el
        lease vencido mientras el runtime se declaraba sano.

        Los estados y la comparación son los mismos que usa `recover_expired()`,
        a propósito: quien detecta y quien recupera deben mirar lo mismo o el
        sensor volvería a mentir.
        """
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                tables = {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if "autonomous_tasks" not in tables:
                    return {
                        "ok": True,
                        "stale_leases": 0,
                        "note": "no_autonomous_tasks_table",
                    }
                stale = conn.execute(
                    """SELECT COUNT(*) FROM autonomous_tasks
                    WHERE status IN ('leased','running')
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at<=?""",
                    (datetime.now(UTC).isoformat(),),
                ).fetchone()[0]
                # Tarea activa que ya nadie puede tomar: `recovered` cuenta como
                # activa, pero `claim_next_task` exige `attempt < max_attempts`.
                # No tiene lease, así que el recuento de arriba no la ve nunca —y
                # mientras siga activa bloquea `enqueue()` por dedup de
                # `(task_type, payload_hash)`—. Así se pararon los backups: un
                # `encrypted_backup` agotado el 2026-08-03 secuestró su tipo 4,5
                # días con el runtime declarándose sano.
                blocked = conn.execute(
                    """SELECT COUNT(*) FROM autonomous_tasks
                    WHERE status='recovered' AND attempt>=max_attempts"""
                ).fetchone()[0]
                return {
                    "ok": stale == 0 and blocked == 0,
                    "stale_leases": int(stale),
                    "blocked_tasks": int(blocked),
                }
        except (sqlite3.Error, OSError) as exc:
            return {"ok": False, "error": type(exc).__name__}

    def _check_vital_chain(self) -> dict[str, Any]:
        """¿Sigue el organismo reconociéndose de punta a punta?

        Los otros cinco sensores miran recursos: disco, memoria, latido, leases,
        cola. Ninguno mira si la cadena que va del pulso al efecto futuro sigue
        entera, y ése es el único fallo que no se nota desde fuera — el sistema
        puede tener disco de sobra, latido puntual y cola vacía justamente
        *porque* un eslabón dejó de producir.

        La comprobación existía y vivía fuera del organismo: `_vital_chain_gaps`
        en `observability/introspection.py`, dentro del informe de deuda, que se
        arma sobre un artefacto de hasta seis horas. Un diagnóstico de hace seis
        horas describe un sistema que ya no existe. Aquí se lee la base viva en
        cada ciclo, que es lo que permite decir «algo no cuadra» y no
        «algo no cuadraba».

        Se reutiliza `VITAL_CHAIN` a propósito. Una segunda lista de eslabones
        escrita aparte es una lista que acabará divergiendo de la primera, y
        entonces habría dos verdades sobre qué es la cadena vital.
        """
        try:
            from triade.observability.introspection import (
                live_table_counts,
                open_readonly,
                recent_activity,
            )
            from triade.observability.runtime_graph import (
                ON_DEMAND_STAGES,
                VITAL_CHAIN,
            )
        except ImportError as exc:
            return {"ok": True, "note": f"sin observabilidad: {type(exc).__name__}"}

        conn = open_readonly(self.db_path)
        if conn is None:
            return {"ok": True, "note": "sin base viva"}
        try:
            filas = live_table_counts(conn)
            frescas = recent_activity(
                conn, [t for _, _, tablas in VITAL_CHAIN for t in tablas]
            )
        except (sqlite3.Error, OSError) as exc:
            return {"ok": False, "error": type(exc).__name__}
        finally:
            conn.close()

        cortes: list[str] = []
        for etapa, _anclas, tablas in VITAL_CHAIN:
            presentes = [t for t in tablas if t in filas]
            total = sum(filas.get(t, 0) for t in presentes)
            if total == 0:
                cortes.append(f"{etapa}: sin filas")
            elif not any(frescas.get(t) for t in presentes):
                # Un eslabón bajo demanda ocioso no es un corte: nadie pidió
                # nada. Sin filas **nunca** sí se cuenta arriba, porque entonces
                # no hay prueba de que haya funcionado jamás.
                if etapa in ON_DEMAND_STAGES:
                    continue
                cortes.append(f"{etapa}: {total} filas, ninguna en 24 h")
        return {
            "ok": not cortes,
            "stages": len(VITAL_CHAIN),
            "broken": cortes,
            "evidence": "SQLite en mode=ro sobre las tablas de cada eslabón",
        }

    def _check_queue(self) -> dict[str, Any]:
        """Trabajo esperando en la cola viva.

        El gemelo de `_check_leases`, con el mismo fallo y encontrado después:
        contaba `worker_tasks.status='pending'`, la cola legacy, retirada por
        trigger en `019_legacy_retirement.sql` y sin una escritura desde el
        2026-07-29. Devolvía `pending: 0` siempre, así que un atasco real no
        podía detectarse: el sensor miraba un cadáver.

        Se cuentan los estados elegibles de la cola v2, no sólo `pending`. Una
        tarea en `retry_wait` o `recovered` también es trabajo esperando, y
        contar sólo uno de los ocho volvería a subestimar la cola — más
        despacio, pero igual.
        """
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                tables = {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if "autonomous_tasks" not in tables:
                    return {
                        "ok": True,
                        "pending": 0,
                        "note": "no_autonomous_tasks_table",
                    }
                marcadores, estados = sql_placeholders(ELIGIBLE)
                pending = conn.execute(
                    f"SELECT COUNT(*) FROM autonomous_tasks WHERE status IN ({marcadores})",
                    estados,
                ).fetchone()[0]
                return {"ok": int(pending) < 100, "pending": int(pending)}
        except (sqlite3.Error, OSError) as exc:
            return {"ok": False, "error": type(exc).__name__}

"""Diagnóstico del aprendizaje continuo, en un solo comando.

Hasta ahora, saber si Tríade estaba aprendiendo de verdad exigía cruzar a mano
`autonomous_tasks`, `learning_queue`, `learning_evidence`,
`learning_retrieval_decisions` y las variables de entorno del proceso vivo. Esa
fricción es la razón por la que un circuito roto sobrevivió semanas pareciendo
sano.

Cada dato declara **de dónde sale y en qué ventana**. Un diagnóstico que no dice
su procedencia es otra pantalla que puede mentir.

`status` sale de las señales, nunca de una impresión:

``off``
    El aprendizaje está apagado por configuración.
``stalled``
    Encendido, con candidatos esperando, y sin progreso en la ventana.
``idle``
    Encendido y sin trabajo pendiente. No es un fallo.
``healthy``
    Encendido y con progreso observable.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from triade.db import sqlite3
from triade.runtime.task_status import ACTIVE

DOCTOR_VERSION = "continuous-learning-doctor-1.0.0"

#: Ventana por defecto de todo lo que aquí se llame «reciente».
DEFAULT_WINDOW_HOURS = 24

LEARNING_TASK_TYPES = (
    "learning_candidate_generation",
    "learning_candidate_deduplication",
    "learning_evidence_generation",
    "pending_learning_review",
)

#: Estados no terminales de la cola gobernada.
#:
#: Era una tupla escrita a mano a la que le faltaban `deferred` y
#: `completion_uncertain`, añadidos después en la cola sin que esta copia se
#: enterara: una tarea diferida era invisible para el doctor y visible para el
#: planificador. Se ordena para que el `IN (...)` sea estable entre ejecuciones.
ACTIVE_STATUSES = tuple(sorted(ACTIVE))


def _cutoff(hours: int) -> str:
    """Corte en el mismo formato ISO que escriben las tablas.

    `datetime('now','-1 day')` de SQLite devuelve `2026-08-01 03:55:12` con
    espacio, y las columnas guardan `...T03:55:12.027832+00:00` con `T`. Como
    `'T' > ' '` en comparación lexicográfica, ese corte deja pasar filas
    anteriores a la ventana.
    """
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()


class ContinuousLearningDoctor:
    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        *,
        window_hours: int = DEFAULT_WINDOW_HOURS,
    ) -> None:
        self.db_path = Path(db_path)
        self.window_hours = int(window_hours)

    # ── acceso ───────────────────────────────────────────────────────
    def _rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        except sqlite3.Error:
            return []
        try:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        except sqlite3.Error:
            return []
        finally:
            conn.close()

    def _one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        filas = self._rows(sql, params)
        return filas[0] if filas else None

    # ── secciones ────────────────────────────────────────────────────
    def _env_file(self) -> dict[str, str]:
        """Variables del `.env`, que es lo que se le pasa al runtime al arrancar."""
        ruta = Path(".env")
        if not ruta.exists():
            return {}
        valores: dict[str, str] = {}
        try:
            for linea in ruta.read_text(encoding="utf-8").splitlines():
                limpia = linea.strip()
                if not limpia or limpia.startswith("#") or "=" not in limpia:
                    continue
                clave, _, valor = limpia.partition("=")
                if clave.strip().startswith("TRIADE_"):
                    valores[clave.strip()] = valor.strip()
        except OSError:
            return {}
        return valores

    def _lookup(self, nombre: str, defecto: str) -> tuple[str, str]:
        """Valor efectivo y **de dónde salió**.

        El diagnóstico se ejecuta casi siempre desde una shell que no tiene las
        variables del runtime: quien las tiene es el proceso de uvicorn, que
        arrancó con `set -a && . ./.env`. Mirar sólo `os.environ` hacía que el
        doctor dijera `off` con el aprendizaje encendido — un falso negativo
        peor que no tener diagnóstico.
        """
        if nombre in os.environ:
            return str(os.environ[nombre]).strip().lower(), "os.environ"
        archivo = self._env_file()
        if nombre in archivo:
            return archivo[nombre].strip().lower(), ".env"
        return defecto, "default"

    def _config(self) -> dict[str, Any]:
        # El defecto del código dejó de ser `0` el 2026-08-28: en producción el
        # aprendizaje continuo va encendido salvo que alguien lo apague. Si aquí
        # siguiera puesto `0`, el diagnóstico diría `off` sobre un organismo que
        # está aprendiendo — el mismo falso negativo que motivó `_lookup`, sólo
        # que un escalón más abajo.
        from triade.learning.post_run import post_run_learning_enabled

        crudo, origen = self._lookup(
            "TRIADE_POST_RUN_LEARNING", "1" if post_run_learning_enabled() else "0"
        )
        concurrencia, origen_conc = self._lookup("TRIADE_WORKER_CONCURRENCY", "1")
        return {
            "learning_enabled": crudo in {"1", "true", "yes", "on"},
            "learning_enabled_raw": crudo,
            "learning_enabled_source": origen,
            "worker_concurrency_enabled": concurrencia in {"1", "true", "yes"},
            "worker_concurrency_source": origen_conc,
            "db_path": str(self.db_path),
            "db_exists": self.db_path.exists(),
            "window_hours": self.window_hours,
            "source": "os.environ, luego .env, luego defecto del código",
        }

    def _tasks(self) -> dict[str, Any]:
        corte = _cutoff(self.window_hours)
        marcadores = ",".join("?" for _ in LEARNING_TASK_TYPES)
        recientes = self._rows(
            f"SELECT task_type,status,COUNT(*) n FROM autonomous_tasks"
            f" WHERE task_type IN ({marcadores}) AND updated_at > ?"
            " GROUP BY 1,2",
            (*LEARNING_TASK_TYPES, corte),
        )
        activas = ",".join("?" for _ in ACTIVE_STATUSES)
        atascadas = self._rows(
            f"SELECT task_id,task_type,status,updated_at,lease_expires_at"
            f" FROM autonomous_tasks WHERE status IN ({activas})"
            " AND updated_at < ? ORDER BY updated_at LIMIT 10",
            (*ACTIVE_STATUSES, _cutoff(1)),
        )
        nunca = [
            t
            for t in LEARNING_TASK_TYPES
            if not self._one(
                "SELECT 1 FROM autonomous_tasks WHERE task_type=? LIMIT 1", (t,)
            )
        ]
        return {
            "recent_by_type": recientes,
            "stuck_over_1h": atascadas,
            "never_executed": nunca,
            "source": "autonomous_tasks",
            "window": f"updated_at > {corte}",
        }

    def _candidates(self) -> dict[str, Any]:
        corte = _cutoff(self.window_hours)
        return {
            "by_status": self._rows(
                "SELECT status,COUNT(*) n FROM learning_queue GROUP BY 1 ORDER BY n DESC"
            ),
            "created_in_window": (
                self._one(
                    "SELECT COUNT(*) n FROM learning_queue WHERE created_at > ?",
                    (corte,),
                )
                or {"n": 0}
            )["n"],
            "latest": self._rows(
                "SELECT candidate_id,source_type,status,risk_level,created_at"
                " FROM learning_queue ORDER BY id DESC LIMIT 5"
            ),
            "source": "learning_queue",
        }

    def _evidence(self) -> dict[str, Any]:
        ultima = self._one(
            "SELECT candidate_id,decision,updated_at FROM learning_evidence"
            " ORDER BY id DESC LIMIT 1"
        )
        return {
            "by_decision": self._rows(
                "SELECT decision,COUNT(*) n FROM learning_evidence GROUP BY 1"
            ),
            "pending_unresolved": (
                self._one(
                    "SELECT COUNT(*) n FROM learning_evidence WHERE decision='pending'"
                )
                or {"n": 0}
            )["n"],
            "latest": ultima,
            "source": "learning_evidence",
        }

    def _consolidated(self) -> dict[str, Any]:
        fila = self._one(
            "SELECT COUNT(*) n, MAX(updated_at) last FROM learning_queue"
            " WHERE status IN ('evidence_verified','stable')"
        ) or {"n": 0, "last": None}
        return {
            "usable_knowledge": fila["n"],
            "last_consolidated_at": fila["last"],
            "source": "learning_queue WHERE status IN ('evidence_verified','stable')",
        }

    def _later_use(self) -> dict[str, Any]:
        ultimo = self._one(
            "SELECT run_id,injected_ids,created_at FROM learning_retrieval_decisions"
            " WHERE injected_ids NOT IN ('[]','') ORDER BY id DESC LIMIT 1"
        )
        corte = _cutoff(self.window_hours)
        n = (
            self._one(
                "SELECT COUNT(*) n FROM learning_retrieval_decisions"
                " WHERE injected_ids NOT IN ('[]','') AND created_at > ?",
                (corte,),
            )
            or {"n": 0}
        )["n"]
        return {
            "injections_in_window": n,
            "last_injection": ultimo,
            "source": "learning_retrieval_decisions",
        }

    def _legacy_route(self) -> dict[str, Any]:
        """¿Sigue la ruta antigua creando aprendizaje en paralelo?"""
        corte = _cutoff(self.window_hours)
        antigua = (
            self._one(
                "SELECT COUNT(*) n FROM learning_queue"
                " WHERE source_type='conversation' AND created_at > ?",
                (corte,),
            )
            or {"n": 0}
        )["n"]
        gobernada = (
            self._one(
                "SELECT COUNT(*) n FROM learning_queue"
                " WHERE source_type='experience' AND created_at > ?",
                (corte,),
            )
            or {"n": 0}
        )["n"]
        volcados = (
            self._one(
                "SELECT COUNT(*) n FROM learning_queue"
                " WHERE content LIKE 'run_id:%' AND content LIKE '%input:%'"
            )
            or {"n": 0}
        )["n"]
        return {
            "legacy_active": antigua > 0,
            "legacy_candidates_in_window": antigua,
            "governed_candidates_in_window": gobernada,
            "transcript_dumps_total": volcados,
            "source": "learning_queue.source_type",
        }

    def _neuron_evaluator(self) -> dict[str, Any]:
        sesiones = self._rows(
            "SELECT state,COUNT(*) n FROM neuron_education_sessions GROUP BY 1"
        )
        aplicaciones = (
            self._one("SELECT COUNT(*) n FROM neuron_education_applications")
            or {"n": 0}
        )["n"]
        return {
            "sessions_by_state": sesiones,
            "applications": aplicaciones,
            "circuit_closes": aplicaciones > 0,
            "source": "neuron_education_sessions / neuron_education_applications",
        }

    def _last_error(self) -> dict[str, Any]:
        fila = self._one(
            "SELECT task_id,task_type,status,last_error,updated_at"
            " FROM autonomous_tasks WHERE last_error IS NOT NULL AND last_error<>''"
            " ORDER BY updated_at DESC LIMIT 1"
        )
        return {"last_error": fila, "source": "autonomous_tasks.last_error"}

    # ── veredicto ────────────────────────────────────────────────────
    @staticmethod
    def _status(
        config: dict[str, Any],
        tasks: dict[str, Any],
        candidates: dict[str, Any],
        later: dict[str, Any],
    ) -> tuple[str, list[str]]:
        motivos: list[str] = []
        if not config["learning_enabled"]:
            return "off", ["TRIADE_POST_RUN_LEARNING no está activado"]

        progreso = sum(int(f["n"]) for f in tasks["recent_by_type"])
        pendientes = sum(
            int(f["n"])
            for f in candidates["by_status"]
            if str(f["status"]) == "internally_checked"
        )

        if tasks["never_executed"]:
            motivos.append(
                "tipos sin ejecutar nunca: " + ", ".join(tasks["never_executed"])
            )
        if tasks["stuck_over_1h"]:
            motivos.append(f"{len(tasks['stuck_over_1h'])} tarea(s) sin avanzar >1 h")

        if progreso == 0:
            if pendientes > 0:
                motivos.append(
                    f"{pendientes} candidatos esperando y ninguna tarea de "
                    "aprendizaje avanzó en la ventana"
                )
                return "stalled", motivos
            return "idle", motivos or ["sin trabajo pendiente"]

        motivos.append(f"{progreso} tareas de aprendizaje avanzaron en la ventana")
        if later["injections_in_window"] == 0:
            motivos.append("ningún saber se inyectó en la ventana")
        return "healthy", motivos

    def diagnose(self) -> dict[str, Any]:
        config = self._config()
        tasks = self._tasks()
        candidates = self._candidates()
        later = self._later_use()
        status, motivos = self._status(config, tasks, candidates, later)
        return {
            "doctor_version": DOCTOR_VERSION,
            "checked_at": datetime.now(UTC).isoformat(),
            "status": status,
            "reasons": motivos,
            "config": config,
            "tasks": tasks,
            "candidates": candidates,
            "evidence": self._evidence(),
            "consolidated": self._consolidated(),
            "later_use": later,
            "legacy_route": self._legacy_route(),
            "neuron_evaluator": self._neuron_evaluator(),
            "errors": self._last_error(),
        }

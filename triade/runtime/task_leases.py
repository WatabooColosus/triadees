"""Cola autónoma con lease atómico, idempotencia y recuperación."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

# El vocabulario vivía aquí, que es donde se escribe. Se movió a
# `task_status.py` para que los demás módulos puedan importarlo en vez de
# redeclararlo —que es lo que venían haciendo, y divergiendo—. Se reexporta con
# los mismos nombres: quien ya lo importaba de aquí no se entera.
from triade.runtime.task_status import (  # noqa: F401
    ACTIVE,
    ALL_STATES,
    TERMINAL,
    TERMINAL_FAILURE,
    TERMINAL_NON_SUCCESS,
    TERMINAL_SUCCESS,
)

MAX_DISPATCH_DEFERRALS = 20


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


class AutonomousTaskStore:
    """Persistencia separada de la cola legacy; nunca reclama con SELECT+UPDATE."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        migrations = [
            Path(__file__).resolve().parents[1]
            / "memory/migrations/009_runtime_resilience.sql",
            Path(__file__).resolve().parents[1]
            / "memory/migrations/012_truthful_task_states.sql",
            Path(__file__).resolve().parents[1]
            / "memory/migrations/013_lease_fencing.sql",
        ]
        with closing(self._connect()) as conn:
            for migration in migrations:
                conn.executescript(migration.read_text(encoding="utf-8"))
            self._ensure_fencing_columns(conn)

    @staticmethod
    def _ensure_fencing_columns(conn: sqlite3.Connection) -> None:
        task_columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(autonomous_tasks)")
        }
        if "lease_generation" not in task_columns:
            conn.execute(
                "ALTER TABLE autonomous_tasks ADD COLUMN lease_generation INTEGER NOT NULL DEFAULT 0"
            )
        transition_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(autonomous_task_transitions)")
        }
        if "lease_generation" not in transition_columns:
            conn.execute(
                "ALTER TABLE autonomous_task_transitions ADD COLUMN lease_generation INTEGER NOT NULL DEFAULT 0"
            )

    def _connect(self) -> sqlite3.Connection:
        """Conexión de vida corta. **Ciérrala tú**: `with closing(...)`.

        `with conn:` NO cierra —abre y cierra transacción— así que cada llamada
        dejaba una conexión viva hasta que el recolector se acordara de ella.
        Con `isolation_level=None` esto es autocommit y los commits son
        explícitos, así que `closing()` no cambia una coma de la semántica: sólo
        libera cuando toca.

        Por qué importa: `AutonomousTaskStore()` se construye en el
        `__init__` de `WorkerTaskQueue`, que se construye en el de
        `WorkerLoop`. Cada worker dejaba conexiones SQLite a merced del GC, y
        con concurrencia el recolector puede finalizarlas desde un hilo distinto
        del que las creó. En py3.11 eso se manifestó como
        `Fatal Python error: Segmentation fault` **durante** `Garbage-collecting`
        —con la pila apuntando aquí— de forma intermitente y sólo con
        `TRIADE_WORKER_CONCURRENCY=1`.
        """
        conn = sqlite3.connect(self.db_path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @staticmethod
    def payload_hash(payload: dict[str, Any]) -> str:
        raw = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
        return hashlib.sha256(raw).hexdigest()

    def enqueue(
        self,
        task_type: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        priority: int = 50,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key_required")
        now = _iso()
        task_id = f"task-{uuid4().hex}"
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM autonomous_tasks WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                conn.commit()
                return self._decode(existing)
            conn.execute(
                """INSERT INTO autonomous_tasks
                (task_id,task_type,idempotency_key,status,priority,created_at,updated_at,max_attempts,payload_json,payload_hash)
                VALUES(?,?,?,'pending',?,?,?,?,?,?)""",
                (
                    task_id,
                    task_type,
                    idempotency_key,
                    int(priority),
                    now,
                    now,
                    max(1, int(max_attempts)),
                    canonical,
                    self.payload_hash(payload),
                ),
            )
            conn.commit()
        return self.get(task_id) or {}

    def claim(
        self,
        worker_id: str,
        *,
        lease_seconds: int = 60,
        excluded_task_types: set[str] | None = None,
    ) -> dict[str, Any] | None:
        if not worker_id.strip():
            raise ValueError("worker_id_required")
        now = _now()
        expires = _iso(now + timedelta(seconds=max(1, lease_seconds)))
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            exclusions = sorted(excluded_task_types or ())
            exclusion_sql = ""
            params: list[Any] = [_iso(now)]
            if exclusions:
                placeholders = ",".join("?" for _ in exclusions)
                exclusion_sql = f" AND task_type NOT IN ({placeholders})"
                params.extend(exclusions)
            params.append(_iso(now))
            row = conn.execute(
                f"""SELECT task_id FROM autonomous_tasks
                WHERE (status IN ('pending','queued','recovered')
                    OR (status IN ('retry_wait','deferred') AND retry_after<=?))
                AND attempt < max_attempts
                {exclusion_sql}
                ORDER BY (priority - MIN(100, CAST((julianday(?) - julianday(created_at))*1440 AS INTEGER))) ASC,
                created_at ASC LIMIT 1""",
                params,
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            changed = conn.execute(
                """UPDATE autonomous_tasks SET status='leased',worker_id=?,lease_acquired_at=?,
                lease_expires_at=?,heartbeat_at=?,attempt=attempt+1,updated_at=?,
                lease_generation=lease_generation+1
                WHERE task_id=? AND status IN ('pending','queued','recovered','retry_wait','deferred')""",
                (worker_id, _iso(now), expires, _iso(now), _iso(now), row["task_id"]),
            ).rowcount
            conn.commit()
        return self.get(str(row["task_id"])) if changed == 1 else None

    def start(self, task_id: str, worker_id: str, lease_generation: int) -> bool:
        return self._owned_update(
            task_id,
            worker_id,
            lease_generation,
            "status='running',heartbeat_at=?,updated_at=?",
            (_iso(), _iso()),
        )

    def claim_task(
        self, task_id: str, worker_id: str, *, lease_seconds: int = 60
    ) -> dict[str, Any] | None:
        """Reclama una tarea concreta de forma atómica para migración legacy."""
        if not task_id.strip() or not worker_id.strip():
            raise ValueError("task_id_and_worker_id_required")
        now = _now()
        now_iso = _iso(now)
        expires = _iso(now + timedelta(seconds=max(1, lease_seconds)))
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            changed = conn.execute(
                """UPDATE autonomous_tasks SET status='leased',worker_id=?,lease_acquired_at=?,
                lease_expires_at=?,heartbeat_at=?,attempt=attempt+1,updated_at=?,
                lease_generation=lease_generation+1
                WHERE task_id=?
                  AND (status IN ('pending','queued','recovered')
                    OR (status IN ('retry_wait','deferred') AND retry_after<=?))
                  AND attempt < max_attempts""",
                (worker_id, now_iso, expires, now_iso, now_iso, task_id, now_iso),
            ).rowcount
            conn.commit()
        return self.get(task_id) if changed == 1 else None

    def renew(
        self,
        task_id: str,
        worker_id: str,
        lease_generation: int,
        *,
        lease_seconds: int = 60,
    ) -> bool:
        now = _now()
        renewed = self._owned_update(
            task_id,
            worker_id,
            lease_generation,
            "lease_expires_at=?,heartbeat_at=?,updated_at=?",
            (
                _iso(now + timedelta(seconds=max(1, lease_seconds))),
                _iso(now),
                _iso(now),
            ),
        )
        with closing(self._connect()) as conn:
            conn.execute(
                """INSERT INTO autonomous_lease_heartbeats
                (task_id,worker_id,lease_generation,renewed,created_at) VALUES(?,?,?,?,?)""",
                (task_id, worker_id, lease_generation, int(renewed), _iso(now)),
            )
        return renewed

    def complete(
        self, task_id: str, worker_id: str, lease_generation: int, result_ref: str
    ) -> bool:
        if not result_ref.strip():
            raise ValueError("completed_requires_result_ref")
        if not Path(result_ref).is_file():
            return False
        return self._terminal_transition(
            task_id, worker_id, lease_generation, "completed", result_ref=result_ref
        )

    def prepare_completion(
        self, task_id: str, worker_id: str, lease_generation: int, result_ref: str
    ) -> bool:
        return self._transition(
            task_id,
            worker_id,
            lease_generation,
            "completion_uncertain",
            reason="artifact_publication_pending",
            result_ref=result_ref,
        )

    def finalize_completion(
        self, task_id: str, worker_id: str, lease_generation: int, result_ref: str
    ) -> bool:
        if not Path(result_ref).is_file():
            return False
        now = _iso()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            changed = conn.execute(
                """UPDATE autonomous_tasks SET status='completed',updated_at=?,
                lease_expires_at=NULL WHERE task_id=? AND worker_id=? AND lease_generation=?
                AND status='completion_uncertain' AND result_ref=?""",
                (now, task_id, worker_id, lease_generation, result_ref),
            ).rowcount
            if changed == 1:
                conn.execute(
                    """INSERT INTO autonomous_task_transitions
                    (task_id,worker_id,lease_generation,from_status,to_status,reason,result_ref,created_at)
                    VALUES(?,?,?,'completion_uncertain','completed','artifacts_published',?,?)""",
                    (task_id, worker_id, lease_generation, result_ref, now),
                )
            conn.commit()
        return changed == 1

    def reconcile_uncertain_completions(self) -> dict[str, int]:
        """Resuelve `completion_uncertain`: o completa, o cierra diciendo por qué.

        Lo que hacía antes era contar las irresolubles (`failed += 1`) y dejarlas
        donde estaban. Como nada más las tocaba, se acumulaban indefinidamente:
        la auditoría en vivo del 2026-07-31 encontró 12, la más antigua de 20
        horas atrás. `completion_uncertain` no es terminal ni activo — es limbo —
        y como la monitorización lo cuenta entre las tareas vivas, el sistema
        **afirmaba actividad que no existía**.

        Sin artefacto no se reintenta: no sabemos si el efecto llegó a aplicarse,
        y repetir un `goal_safe_command` podría aplicarlo dos veces. Se cierra
        como `dead_letter` con la razón explícita, y la decisión de reencolar
        queda en manos de un humano que pueda mirar el caso.
        """
        completed = 0
        dead_lettered = 0
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """SELECT task_id,worker_id,lease_generation,result_ref
                FROM autonomous_tasks WHERE status='completion_uncertain'"""
            ).fetchall()
        for row in rows:
            ref = str(row["result_ref"] or "")
            task_id = str(row["task_id"])
            if ref and Path(ref).is_file():
                completed += int(
                    self.finalize_completion(
                        task_id,
                        str(row["worker_id"]),
                        int(row["lease_generation"]),
                        ref,
                    )
                )
            else:
                dead_lettered += int(
                    self._close_uncertain_without_artifact(
                        task_id,
                        str(row["worker_id"] or ""),
                        int(row["lease_generation"]),
                    )
                )
        return {
            "completed": completed,
            # Se conserva la clave por compatibilidad con quien la lea: ahora
            # siempre es 0, porque ninguna se queda sin resolver.
            "still_uncertain": 0,
            "dead_lettered": dead_lettered,
        }

    def _close_uncertain_without_artifact(
        self, task_id: str, worker_id: str, lease_generation: int
    ) -> bool:
        now = _iso()
        reason = "uncertain_without_artifact:no_evidence_of_completion"
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            changed = conn.execute(
                """UPDATE autonomous_tasks SET status='dead_letter',
                last_error=COALESCE(last_error||'; ','')||?,
                lease_expires_at=NULL,updated_at=?
                WHERE task_id=? AND status='completion_uncertain'""",
                (reason, now, task_id),
            ).rowcount
            if changed == 1:
                conn.execute(
                    """INSERT INTO autonomous_task_transitions
                    (task_id,worker_id,lease_generation,from_status,to_status,reason,created_at)
                    VALUES(?,?,?,'completion_uncertain','dead_letter',?,?)""",
                    (task_id, worker_id, lease_generation, reason, now),
                )
            conn.commit()
        return changed == 1

    def block(
        self, task_id: str, worker_id: str, lease_generation: int, reason: str
    ) -> bool:
        return self._terminal_transition(
            task_id, worker_id, lease_generation, "blocked", reason=reason
        )

    def skip(
        self, task_id: str, worker_id: str, lease_generation: int, reason: str
    ) -> bool:
        return self._terminal_transition(
            task_id, worker_id, lease_generation, "skipped", reason=reason
        )

    def mark_dry_run(
        self, task_id: str, worker_id: str, lease_generation: int, reason: str
    ) -> bool:
        return self._terminal_transition(
            task_id, worker_id, lease_generation, "dry_run", reason=reason
        )

    def cancel(
        self, task_id: str, worker_id: str, lease_generation: int, reason: str
    ) -> bool:
        return self._terminal_transition(
            task_id, worker_id, lease_generation, "cancelled", reason=reason
        )

    def mark_observed(
        self, task_id: str, worker_id: str, lease_generation: int, reason: str
    ) -> bool:
        return self._terminal_transition(
            task_id, worker_id, lease_generation, "observed", reason=reason
        )

    def mark_timeout(
        self,
        task_id: str,
        worker_id: str,
        lease_generation: int,
        reason: str,
        *,
        retryable: bool = True,
    ) -> bool:
        if retryable:
            outcome = self.fail(
                task_id, worker_id, lease_generation, f"timeout:{reason}"
            )
            return outcome.get("status") in {"retry_wait", "dead_letter"}
        return self._terminal_transition(
            task_id, worker_id, lease_generation, "timeout", reason=reason
        )

    def mark_lease_lost(
        self, task_id: str, worker_id: str, lease_generation: int, reason: str
    ) -> bool:
        return self._terminal_transition(
            task_id, worker_id, lease_generation, "lease_lost", reason=reason
        )

    def defer(
        self,
        task_id: str,
        worker_id: str,
        lease_generation: int,
        reason: str,
        *,
        delay_seconds: int = 30,
    ) -> bool:
        retry_after = _iso(_now() + timedelta(seconds=max(0, delay_seconds)))
        return self._transition(
            task_id,
            worker_id,
            lease_generation,
            "deferred",
            reason=reason,
            retry_after=retry_after,
        )

    def defer_unstarted(
        self,
        task_id: str,
        worker_id: str,
        lease_generation: int,
        reason: str,
        *,
        delay_seconds: int = 5,
    ) -> bool:
        """Devuelve a la cola una tarea arrendada que nunca llegó a ejecutarse.

        `claim()` incrementa `attempt` al arrendar, y `defer()` deja ese intento
        consumido. Para una tarea que **corrió** eso es correcto: el intento
        existió. Pero cuando se rechaza el despacho —carril lleno, clave de
        exclusión tomada, backpressure— la tarea no ha hecho absolutamente nada.
        Contar ese intento gastaría los tres disponibles por el mero hecho de
        haber esperado turno, y mataría la tarea sin haberla intentado jamás.

        Por eso aquí se descuenta el intento al devolverla. La distinción
        importa más cuanto más concurrencia hay: con varios carriles compitiendo,
        los rechazos por turno son normales y no deben parecer fracasos.
        """
        now = _iso()
        retry_after = _iso(_now() + timedelta(seconds=max(0, delay_seconds)))
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                """SELECT status,attempt FROM autonomous_tasks
                WHERE task_id=? AND worker_id=? AND lease_generation=?""",
                (task_id, worker_id, lease_generation),
            ).fetchone()
            if current is None or str(current["status"]) != "leased":
                # Si ya está 'running' es que alguien la arrancó: no se toca.
                conn.commit()
                return False
            deferrals = int(
                conn.execute(
                    """SELECT COUNT(*) FROM autonomous_task_transitions
                    WHERE task_id=? AND to_status='deferred'""",
                    (task_id,),
                ).fetchone()[0]
            )
            if deferrals >= MAX_DISPATCH_DEFERRALS:
                changed = conn.execute(
                    """UPDATE autonomous_tasks SET status='dead_letter',
                    last_error='dispatch_livelock_guard',lease_expires_at=NULL,updated_at=?
                    WHERE task_id=? AND worker_id=? AND lease_generation=? AND status='leased'""",
                    (now, task_id, worker_id, lease_generation),
                ).rowcount
                if changed == 1:
                    conn.execute(
                        """INSERT INTO autonomous_task_transitions
                        (task_id,worker_id,lease_generation,from_status,to_status,reason,created_at)
                        VALUES(?,?,?,'leased','dead_letter','dispatch_livelock_guard',?)""",
                        (task_id, worker_id, lease_generation, now),
                    )
                conn.commit()
                return changed == 1
            previous = str(current["status"])
            changed = conn.execute(
                """UPDATE autonomous_tasks
                SET status='deferred',retry_after=?,last_error=?,
                    attempt=MAX(0,attempt-1),lease_expires_at=NULL,updated_at=?
                WHERE task_id=? AND worker_id=? AND lease_generation=? AND status='leased'""",
                (retry_after, reason, now, task_id, worker_id, lease_generation),
            ).rowcount
            if changed == 1:
                conn.execute(
                    """INSERT INTO autonomous_task_transitions
                    (task_id,worker_id,lease_generation,from_status,to_status,reason,created_at)
                    VALUES(?,?,?,?,'deferred',?,?)""",
                    (task_id, worker_id, lease_generation, previous, reason, now),
                )
            conn.commit()
        return changed == 1

    def fail(
        self,
        task_id: str,
        worker_id: str,
        lease_generation: int,
        error: str,
        *,
        base_delay_seconds: int = 30,
    ) -> dict[str, Any]:
        task = self.get(task_id)
        if (
            not task
            or task.get("worker_id") != worker_id
            or int(task.get("lease_generation") or -1) != lease_generation
        ):
            return {"status": "not_owner"}
        dead = int(task["attempt"]) >= int(task["max_attempts"])
        status = "dead_letter" if dead else "retry_wait"
        retry = (
            None
            if dead
            else _iso(
                _now()
                + timedelta(
                    seconds=base_delay_seconds * (2 ** max(0, int(task["attempt"]) - 1))
                )
            )
        )
        transitioned = self._transition(
            task_id,
            worker_id,
            lease_generation,
            status,
            reason=error[:2000],
            retry_after=retry,
        )
        if not transitioned:
            return {"status": "not_owner"}
        return self.get(task_id) or {}

    def _terminal_transition(
        self,
        task_id: str,
        worker_id: str,
        lease_generation: int,
        status: str,
        *,
        reason: str | None = None,
        result_ref: str | None = None,
    ) -> bool:
        if status not in TERMINAL:
            raise ValueError(f"unknown_terminal_status:{status}")
        return self._transition(
            task_id,
            worker_id,
            lease_generation,
            status,
            reason=reason,
            result_ref=result_ref,
        )

    def _transition(
        self,
        task_id: str,
        worker_id: str,
        lease_generation: int,
        status: str,
        *,
        reason: str | None = None,
        result_ref: str | None = None,
        retry_after: str | None = None,
    ) -> bool:
        if status not in ALL_STATES:
            raise ValueError(f"unknown_status:{status}")
        now = _iso()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                """SELECT status FROM autonomous_tasks
                WHERE task_id=? AND worker_id=? AND lease_generation=?""",
                (task_id, worker_id, lease_generation),
            ).fetchone()
            if current is None or str(current["status"]) not in {"leased", "running"}:
                conn.commit()
                return False
            previous = str(current["status"])
            changed = conn.execute(
                """UPDATE autonomous_tasks SET status=?,retry_after=?,last_error=?,result_ref=?,
                lease_expires_at=NULL,updated_at=? WHERE task_id=? AND worker_id=?
                AND lease_generation=? AND status IN ('leased','running')""",
                (
                    status,
                    retry_after,
                    reason,
                    result_ref,
                    now,
                    task_id,
                    worker_id,
                    lease_generation,
                ),
            ).rowcount
            if changed == 1:
                conn.execute(
                    """INSERT INTO autonomous_task_transitions
                    (task_id,worker_id,lease_generation,from_status,to_status,reason,result_ref,created_at)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        task_id,
                        worker_id,
                        lease_generation,
                        previous,
                        status,
                        reason,
                        result_ref,
                        now,
                    ),
                )
            conn.commit()
        return changed == 1

    def recover_expired(self) -> list[str]:
        now = _iso()
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT task_id FROM autonomous_tasks WHERE status IN ('leased','running') AND lease_expires_at<=?",
                (now,),
            ).fetchall()
            ids = [str(row["task_id"]) for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(
                    f"""UPDATE autonomous_tasks SET status='recovered',worker_id=NULL,lease_acquired_at=NULL,
                    lease_expires_at=NULL,heartbeat_at=NULL,last_error='expired_lease_recovered',updated_at=?
                    WHERE task_id IN ({placeholders})""",
                    (now, *ids),
                )
            conn.commit()
        return ids

    def recover_orphaned_tasks(
        self,
        lock_file: Path | None = None,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Recupera tareas huérfanas de autonomous_tasks tras reinicio del worker.

        Tratamiento por estado:
        - leased: → recovered si lock stale/inexistente o lease expirado
        - running: clasifica → recovered (solo lectura) o completion_uncertain (efectos)
        - retry_wait: preserva status, attempt, retry_after, last_error
        - deferred: preserva status, retry_after
        - completion_uncertain: reconcilia artifacts existentes; mantiene si ambiguo

        Nunca:
        - resetea attempt a 0
        - borra last_error
        - convierte retry_wait/deferred a pending
        - toca tareas con propietario vivo
        """
        now = now or datetime.now(UTC)
        now_iso = _iso(now)

        result: dict[str, Any] = {
            "leased_recovered": 0,
            "running_recovered": 0,
            "running_uncertain": 0,
            "retry_wait_preserved": 0,
            "deferred_preserved": 0,
            "uncertain_completed": 0,
            "uncertain_quarantined": 0,
            "fencing_invalidated": 0,
        }

        # ── 1. Verificar propietario vivo ──────────────────────────
        if lock_file and lock_file.exists():
            from triade.runtime.process_lock import RuntimeProcessLock

            inspection = RuntimeProcessLock.inspect(lock_file)
            if inspection.status == "live":
                return {"status": "live_owner", "pid": inspection.pid, **result}

        # ── 2. Reconciliar completion_uncertain existentes ──────────
        reconciled = self.reconcile_uncertain_completions()
        result["uncertain_completed"] = reconciled["completed"]
        # "Cuarentenadas" son ahora las que se cerraron como `dead_letter` por no
        # tener artefacto. Antes esta cifra contaba las que se quedaban en limbo,
        # que es precisamente lo que ya no ocurre.
        result["uncertain_quarantined"] = reconciled["dead_lettered"]

        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")

            def _record(
                task_id: str,
                worker_id: str | None,
                lease_gen: int,
                from_st: str,
                to_st: str,
                reason: str,
            ) -> None:
                conn.execute(
                    """INSERT INTO autonomous_task_transitions
                    (task_id,worker_id,lease_generation,from_status,to_status,reason,created_at)
                    VALUES(?,?,?,?,?,?,?)""",
                    (task_id, worker_id, lease_gen, from_st, to_st, reason, now_iso),
                )

            # ── 3. leased ──────────────────────────────────────────
            for row in conn.execute(
                """SELECT task_id,worker_id,lease_generation,lease_expires_at,attempt,
                         last_error,heartbeat_at
                 FROM autonomous_tasks WHERE status='leased'"""
            ).fetchall():
                tid = str(row["task_id"])
                wid = str(row["worker_id"]) if row["worker_id"] else None
                lgen = int(row["lease_generation"])
                expires = row["lease_expires_at"]
                expired = expires and expires <= now_iso

                if not expired:
                    conn.commit()
                    return {"status": "live_lease", **result}

                conn.execute(
                    """UPDATE autonomous_tasks SET status='recovered',
                    worker_id=NULL,lease_acquired_at=NULL,lease_expires_at=NULL,
                    heartbeat_at=NULL,updated_at=?
                    WHERE task_id=? AND status='leased'""",
                    (now_iso, tid),
                )
                _record(
                    tid, wid, lgen, "leased", "recovered", "orphaned_lease_recovered"
                )
                result["leased_recovered"] += 1
                result["fencing_invalidated"] += 1

            # ── 4. running ─────────────────────────────────────────
            for row in conn.execute(
                """SELECT task_id,worker_id,lease_generation,lease_expires_at,attempt,
                         last_error,result_ref,payload_hash
                 FROM autonomous_tasks WHERE status='running'"""
            ).fetchall():
                tid = str(row["task_id"])
                wid = str(row["worker_id"]) if row["worker_id"] else None
                lgen = int(row["lease_generation"])
                expires = row["lease_expires_at"]
                expired = expires and expires <= now_iso

                if not expired:
                    conn.commit()
                    return {"status": "live_lease", **result}

                ref = str(row["result_ref"] or "")
                has_artifact = ref and Path(ref).is_file()

                if has_artifact:
                    conn.execute(
                        """UPDATE autonomous_tasks SET status='completed',
                        lease_expires_at=NULL,updated_at=?
                        WHERE task_id=? AND status='running' AND result_ref=?""",
                        (now_iso, tid, ref),
                    )
                    _record(
                        tid,
                        wid,
                        lgen,
                        "running",
                        "completed",
                        "artifact_found_during_recovery",
                    )
                    result["running_recovered"] += 1
                else:
                    conn.execute(
                        """UPDATE autonomous_tasks SET status='completion_uncertain',
                        last_error=COALESCE(last_error||'; ','')||'recovery:no_artifact_found',
                        updated_at=?
                        WHERE task_id=? AND status='running'""",
                        (now_iso, tid),
                    )
                    _record(
                        tid,
                        wid,
                        lgen,
                        "running",
                        "completion_uncertain",
                        "recovery_no_artifact",
                    )
                    result["running_uncertain"] += 1
                result["fencing_invalidated"] += 1

            # ── 5. retry_wait: preservar, solo limpiar owner ───────
            for row in conn.execute(
                """SELECT task_id,worker_id,lease_generation,attempt,
                         retry_after,last_error
                 FROM autonomous_tasks WHERE status='retry_wait'"""
            ).fetchall():
                tid = str(row["task_id"])
                wid = str(row["worker_id"]) if row["worker_id"] else None
                lgen = int(row["lease_generation"])
                if wid:
                    conn.execute(
                        """UPDATE autonomous_tasks SET worker_id=NULL,
                        lease_acquired_at=NULL,lease_expires_at=NULL,
                        heartbeat_at=NULL,updated_at=?
                        WHERE task_id=? AND status='retry_wait'""",
                        (now_iso, tid),
                    )
                    _record(
                        tid,
                        wid,
                        lgen,
                        "retry_wait",
                        "retry_wait",
                        "stale_ownership_cleaned",
                    )
                result["retry_wait_preserved"] += 1

            # ── 6. deferred: preservar, solo limpiar owner ────────
            for row in conn.execute(
                """SELECT task_id,worker_id,lease_generation,
                         retry_after,last_error
                 FROM autonomous_tasks WHERE status='deferred'"""
            ).fetchall():
                tid = str(row["task_id"])
                wid = str(row["worker_id"]) if row["worker_id"] else None
                lgen = int(row["lease_generation"])
                if wid:
                    conn.execute(
                        """UPDATE autonomous_tasks SET worker_id=NULL,
                        lease_acquired_at=NULL,lease_expires_at=NULL,
                        heartbeat_at=NULL,updated_at=?
                        WHERE task_id=? AND status='deferred'""",
                        (now_iso, tid),
                    )
                    _record(
                        tid,
                        wid,
                        lgen,
                        "deferred",
                        "deferred",
                        "stale_ownership_cleaned",
                    )
                result["deferred_preserved"] += 1

            # ── 7. completion_uncertain restantes (no reconciliables) ──
            for row in conn.execute(
                """SELECT task_id,worker_id,lease_generation,result_ref
                 FROM autonomous_tasks WHERE status='completion_uncertain'"""
            ).fetchall():
                ref = str(row["result_ref"] or "")
                if not ref or not Path(ref).is_file():
                    result["uncertain_quarantined"] += 1

            conn.commit()

        result["status"] = "recovered"
        return result

    def get(self, task_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM autonomous_tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        return self._decode(row) if row else None

    def _owned_update(
        self,
        task_id: str,
        worker_id: str,
        lease_generation: int,
        assignment: str,
        values: tuple[Any, ...],
    ) -> bool:
        with closing(self._connect()) as conn:
            changed = conn.execute(
                f"UPDATE autonomous_tasks SET {assignment} WHERE task_id=? AND worker_id=? AND lease_generation=? AND status IN ('leased','running')",
                (*values, task_id, worker_id, lease_generation),
            ).rowcount
        return changed == 1

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

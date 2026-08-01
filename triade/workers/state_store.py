"""Persistencia SQLite para Triade Living Workers."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now
from triade.core.error_bus import prune_worker_events
from triade.runtime.process_lock import RuntimeProcessLock
from triade.runtime.task_leases import AutonomousTaskStore

from .contracts import WorkerRunConfig, WorkerTask


class WorkerStateStore:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        repo_root = Path(__file__).resolve().parents[2]
        self.schema_path = repo_root / "triade/memory/schemas.sql"
        self.migration_paths = [
            repo_root / "triade/memory/migrations/003_living_workers.sql",
            repo_root / "triade/memory/migrations/014_legacy_v2_bridge.sql",
            repo_root / "triade/memory/migrations/019_legacy_retirement.sql",
        ]
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        # `busy_timeout` es lo que separa "esperar mi turno" de "database is
        # locked". Sin él, en cuanto dos tareas escriben a la vez —y con
        # concurrencia gobernada eso es lo normal, no la excepción— la segunda
        # falla al instante en vez de reintentar. `AutonomousTaskStore` ya lo
        # hacía; este store no, y era el punto por donde iba a romperse.
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        if not self.schema_path.exists():
            raise FileNotFoundError(
                f"No existe el esquema de memoria: {self.schema_path}"
            )
        with self._connect() as conn:
            conn.executescript(self.schema_path.read_text(encoding="utf-8"))
            for migration in self.migration_paths:
                if migration.exists():
                    self._apply_migration(conn, migration)

    @staticmethod
    def _apply_migration(conn: sqlite3.Connection, migration: Path) -> None:
        if migration.name != "014_legacy_v2_bridge.sql":
            conn.executescript(migration.read_text(encoding="utf-8"))
            return
        columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(worker_tasks)")
        }
        additions = {
            "autonomous_task_id": "TEXT",
            "migration_status": "TEXT NOT NULL DEFAULT 'pending'",
            "delegated_at": "TEXT",
            "reconciled_at": "TEXT",
            "migration_error": "TEXT",
        }
        for name, declaration in additions.items():
            if name not in columns:
                conn.execute(
                    f"ALTER TABLE worker_tasks ADD COLUMN {name} {declaration}"
                )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_worker_tasks_autonomous_task ON worker_tasks(autonomous_task_id) WHERE autonomous_task_id IS NOT NULL"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_worker_tasks_migration ON worker_tasks(migration_status,status)"
        )

    def create_worker_run(
        self, run_ref: str, config: WorkerRunConfig, artifact_dir: str | Path
    ) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO worker_runs
                (run_ref, status, mode, dry_run, max_iterations, sleep_seconds, started_at, artifact_dir, summary_json)
                VALUES (?, 'running', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_ref,
                    "daemon" if config.daemon else "once",
                    1 if config.dry_run else 0,
                    config.max_iterations,
                    config.sleep_seconds,
                    utc_now(),
                    str(artifact_dir),
                    json.dumps({"iterations": 0}, ensure_ascii=False),
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO runs (run_id, source, user_input, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    run_ref,
                    "worker",
                    "Triade Living Workers background cycle",
                    "created",
                    utc_now(),
                ),
            )
        return self.get_worker_run(run_ref) or {}

    def finish_worker_run(
        self,
        run_ref: str,
        status: str,
        summary: dict[str, Any],
        error: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE worker_runs SET status = ?, finished_at = ?, summary_json = ?, error = ? WHERE run_ref = ?",
                (
                    status,
                    utc_now(),
                    json.dumps(summary, ensure_ascii=False),
                    error,
                    run_ref,
                ),
            )
            conn.execute(
                "UPDATE runs SET status = ?, closed_at = ? WHERE run_id = ?",
                (status, utc_now(), run_ref),
            )

    def get_worker_run(self, run_ref: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM worker_runs WHERE run_ref = ?", (run_ref,)
            ).fetchone()
        return self._decode(row) if row else None

    def list_worker_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM worker_runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._decode(row) for row in rows]

    def enqueue_task(
        self,
        task_type: str,
        payload: dict[str, Any] | None = None,
        priority: int = 50,
        run_ref: str | None = None,
    ) -> WorkerTask:
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO worker_tasks (task_type, status, priority, payload_json, created_at, run_ref)
                VALUES (?, 'pending', ?, ?, ?, ?)""",
                (
                    task_type,
                    int(priority),
                    json.dumps(payload or {}, ensure_ascii=False),
                    utc_now(),
                    run_ref,
                ),
            )
            if cursor.lastrowid is None:
                raise sqlite3.DatabaseError("worker_task_insert_without_id")
            task_id = int(cursor.lastrowid or -1)
        return self.get_task(task_id) or WorkerTask(
            id=task_id, task_type=task_type, payload=payload or {}, priority=priority
        )

    def claim_next_task(self) -> WorkerTask | None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM worker_tasks WHERE status = 'pending' ORDER BY priority ASC, id ASC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE worker_tasks SET status='claimed',migration_status='delegating',started_at=? WHERE id=? AND status='pending'",
                (utc_now(), row["id"]),
            )
        task = self.get_task(int(row["id"]))
        return task

    def link_delegated_task(self, legacy_id: int, autonomous_task_id: str) -> bool:
        with self._connect() as conn:
            changed = conn.execute(
                """UPDATE worker_tasks SET autonomous_task_id=?,migration_status='delegated',
                delegated_at=?,migration_error=NULL WHERE id=? AND migration_status IN ('delegating','delegated')""",
                (autonomous_task_id, utc_now(), legacy_id),
            ).rowcount
        return changed == 1

    def return_delegation_to_pending(self, legacy_id: int, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE worker_tasks SET status='pending',migration_status='pending',
                started_at=NULL,migration_error=? WHERE id=? AND migration_status IN ('delegating','delegated')""",
                (error[:2000], legacy_id),
            )

    def mirror_v2_terminal(
        self,
        legacy_id: int,
        autonomous_task_id: str,
        status: str,
        result: dict[str, Any],
        *,
        run_ref: str,
    ) -> bool:
        with self._connect() as conn:
            canonical = conn.execute(
                "SELECT status FROM autonomous_tasks WHERE task_id=?",
                (autonomous_task_id,),
            ).fetchone()
        if canonical is None or str(canonical["status"]) != status:
            return False
        legacy_status = status
        migration_status = (
            "mirrored_completed" if status == "completed" else "mirrored_failed"
        )
        with self._connect() as conn:
            changed = conn.execute(
                """UPDATE worker_tasks SET status=?,result_json=?,finished_at=?,run_ref=?,
                migration_status=?,reconciled_at=?,migration_error=NULL
                WHERE id=? AND autonomous_task_id=? AND migration_status='delegated'""",
                (
                    legacy_status,
                    json.dumps(result, ensure_ascii=False),
                    utc_now(),
                    run_ref,
                    migration_status,
                    utc_now(),
                    legacy_id,
                    autonomous_task_id,
                ),
            ).rowcount
        return changed == 1

    def get_task(self, task_id: int) -> WorkerTask | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM worker_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return self._task_from_row(row) if row else None

    def list_tasks(
        self, status: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM worker_tasks WHERE status = ? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM worker_tasks ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._task_from_row(row).to_dict() for row in rows]

    def finish_task(
        self,
        task_id: int,
        status: str,
        result: dict[str, Any] | None = None,
        safety_status: str | None = None,
        error: str | None = None,
        run_ref: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE worker_tasks SET status = ?, result_json = ?, safety_status = ?, finished_at = ?, error = ?, run_ref = COALESCE(?, run_ref)
                WHERE id = ?""",
                (
                    status,
                    json.dumps(result or {}, ensure_ascii=False),
                    safety_status,
                    utc_now(),
                    error,
                    run_ref,
                    task_id,
                ),
            )

    def record_event(
        self,
        event_type: str,
        message: str,
        *,
        run_ref: str | None = None,
        task_id: int | None = None,
        task_type: str | None = None,
        status: str = "ok",
        payload: dict[str, Any] | None = None,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO worker_events (run_ref, task_id, task_type, event_type, status, message, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_ref,
                    task_id,
                    task_type,
                    event_type,
                    status,
                    message,
                    json.dumps(payload or {}, ensure_ascii=False),
                    utc_now(),
                ),
            )
            prune_worker_events(conn)
            if cursor.lastrowid is None:
                raise sqlite3.DatabaseError("worker_event_insert_without_id")
            return int(cursor.lastrowid or -1)

    def list_events(
        self, limit: int = 50, run_ref: str | None = None
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if run_ref:
                rows = conn.execute(
                    "SELECT * FROM worker_events WHERE run_ref = ? ORDER BY id DESC LIMIT ?",
                    (run_ref, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM worker_events ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._decode(row) for row in rows]

    def set_state(self, key: str, value: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO worker_state (key, value_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at""",
                (key, json.dumps(value, ensure_ascii=False), utc_now()),
            )

    def get_state(self, key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM worker_state WHERE key = ?", (key,)
            ).fetchone()
        return self._decode(row).get("value_json") if row else None

    def status(self) -> dict[str, Any]:
        with self._connect() as conn:
            task_counts = {
                row["status"]: int(row["c"])
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS c FROM worker_tasks GROUP BY status"
                ).fetchall()
            }
            run_counts = {
                row["status"]: int(row["c"])
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS c FROM worker_runs GROUP BY status"
                ).fetchall()
            }
        recent_runs = self.list_worker_runs(limit=1)
        last_run: dict[str, Any] | None = recent_runs[0] if recent_runs else None
        return {
            "status": "ok",
            "mode": "triade-living-workers",
            "task_counts": task_counts,
            "run_counts": run_counts,
            "last_run": last_run,
            "state": self.get_state("workers") or {},
        }

    def _run_still_has_work_in_flight(self, run_ref: str) -> bool:
        """¿Le queda a este run trabajo de verdad en vuelo?

        Dos fuentes, porque hay dos caminos de ejecución:

        - `worker_tasks` reclamadas o corriendo por este run;
        - `autonomous_tasks` arrendadas a este run (`worker_id = run_ref`) con
          el lease **sin caducar**. La fila sola no basta: un worker muerto a
          media tarea la dejaría ahí para siempre, que es el mismo agujero por
          otra puerta.
        """
        now = utc_now()
        with self._connect() as conn:
            pending = conn.execute(
                "SELECT 1 FROM worker_tasks WHERE run_ref = ? AND status IN ('claimed','running') LIMIT 1",
                (run_ref,),
            ).fetchone()
            if pending is not None:
                return True
            try:
                leased = conn.execute(
                    """SELECT 1 FROM autonomous_tasks
                    WHERE worker_id = ? AND status IN ('leased','running')
                      AND lease_expires_at IS NOT NULL AND lease_expires_at > ?
                    LIMIT 1""",
                    (run_ref, now),
                ).fetchone()
            except sqlite3.OperationalError:
                # La tabla de leases puede no existir todavía en una base recién
                # creada. Sin ella no hay trabajo en vuelo que demostrar.
                return False
        return leased is not None

    def _retained_lock_still_holds_authority(self, run_ref: str | None) -> bool:
        """¿Puede este lock seguir mandando, con su proceso vivo?

        La autoridad del runtime pertenece a un RUN, no a un proceso. Antes se
        devolvía `live_owner` con sólo ver el PID vivo, y en el runtime
        siempre-activo ese PID es el de `uvicorn`: un run cerrado hace horas
        mantenía bloqueado el sistema entero mientras la app siguiera en pie.

        Se conserva la autoridad —dirección conservadora— salvo que se pueda
        **demostrar** que ya no toca:

        - sin `run_ref`: lock de una versión anterior, no hay nada que probar;
        - run desconocido en esta base: tampoco se puede probar (fencing: no se
          le quita el lock a quien no sabemos que terminó);
        - run no terminal: está trabajando;
        - run terminal con trabajo en vuelo: sus tareas siguen escribiendo.

        Sólo cae en el caso restante: run terminal y sin una sola tarea viva.
        """
        if not run_ref:
            return True
        run = self.get_worker_run(run_ref)
        if run is None:
            return True
        if str(run.get("status") or "") in ("running", ""):
            return True
        return self._run_still_has_work_in_flight(run_ref)

    def recover_interrupted_runtime(self, lock_file: str | Path) -> dict[str, Any]:
        """Recupera locks/runs huérfanos y compacta la cola pendiente.

        Un lock es intocable mientras su dueño mande de verdad. Que el PID esté
        vivo ya no basta: ver `_retained_lock_still_holds_authority`. Conserva
        una tarea por clave lógica para replay seguro.
        """
        lock = Path(lock_file)
        stale_pid: int | None = None
        if lock.exists():
            inspection = RuntimeProcessLock.inspect(lock)
            stale_pid = inspection.pid
            if inspection.status == "invalid":
                return {"status": "invalid_lock", "pid": None, "deduplicated": 0}
            if (
                inspection.status == "live"
                and self._retained_lock_still_holds_authority(inspection.run_ref)
            ):
                return {
                    "status": "live_owner",
                    "pid": stale_pid,
                    "run_ref": inspection.run_ref,
                    "deduplicated": 0,
                }
            try:
                lock.unlink()
            except FileNotFoundError:
                pass

        with self._connect() as conn:
            conn.execute("UPDATE worker_tasks SET status='completed' WHERE status='ok'")
            conn.execute("UPDATE worker_tasks SET status='failed' WHERE status='error'")
            interrupted = conn.execute(
                "UPDATE worker_runs SET status='interrupted', finished_at=?, error=COALESCE(error, 'stale_worker_lock_recovered') WHERE status='running'",
                (utc_now(),),
            ).rowcount
            conn.execute(
                "UPDATE worker_tasks SET status='pending', started_at=NULL, error=NULL WHERE status IN ('claimed','running')"
            )
            rows = conn.execute(
                "SELECT id, task_type, payload_json FROM worker_tasks WHERE status='pending' ORDER BY id ASC"
            ).fetchall()
            seen: set[str] = set()
            duplicate_ids: list[int] = []
            for row in rows:
                payload = json.loads(row["payload_json"] or "{}")
                logical = self._logical_task_key(str(row["task_type"]), payload)
                if logical in seen:
                    duplicate_ids.append(int(row["id"]))
                else:
                    seen.add(logical)
            for task_id in duplicate_ids:
                conn.execute(
                    "UPDATE worker_tasks SET status='skipped', finished_at=?, error='duplicate_pending_task_recovered' WHERE id=?",
                    (utc_now(), task_id),
                )

        # Recuperación gobernada de autonomous_tasks v2
        autonomous = AutonomousTaskStore(self.db_path).recover_orphaned_tasks(
            lock_file=lock if stale_pid is not None else None,
        )
        if autonomous.get("status") in ("live_owner", "live_lease"):
            return {
                "status": "live_owner",
                "pid": autonomous.get("pid"),
                "deduplicated": 0,
            }

        return {
            "status": "recovered" if stale_pid is not None else "clean",
            "stale_pid": stale_pid,
            "interrupted_runs": interrupted,
            "deduplicated": len(duplicate_ids),
            "autonomous_tasks": {
                "leased_recovered": autonomous.get("leased_recovered", 0),
                "running_recovered": autonomous.get("running_recovered", 0),
                "running_uncertain": autonomous.get("running_uncertain", 0),
                "retry_wait_preserved": autonomous.get("retry_wait_preserved", 0),
                "deferred_preserved": autonomous.get("deferred_preserved", 0),
                "uncertain_completed": autonomous.get("uncertain_completed", 0),
                "uncertain_quarantined": autonomous.get("uncertain_quarantined", 0),
                "fencing_invalidated": autonomous.get("fencing_invalidated", 0),
            },
        }

    def find_active_equivalent(
        self, task_type: str, payload: dict[str, Any]
    ) -> WorkerTask | None:
        logical = self._logical_task_key(task_type, payload)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM worker_tasks WHERE task_type=? AND status IN ('pending','running','claimed') ORDER BY id ASC",
                (task_type,),
            ).fetchall()
        for row in rows:
            candidate = self._task_from_row(row)
            if (
                self._logical_task_key(candidate.task_type, candidate.payload)
                == logical
            ):
                return candidate
        return None

    @staticmethod
    def _logical_task_key(task_type: str, payload: dict[str, Any]) -> str:
        identity = {
            key: payload.get(key)
            for key in (
                "goal_id",
                "goal_step_id",
                "mission_id",
                "neuron_id",
                "candidate_id",
                "related_candidate_id",
                "command_key",
            )
            if payload.get(key) is not None
        }
        # Tareas baseline solo necesitan una instancia activa por tipo.
        return f"{task_type}:{json.dumps(identity, sort_keys=True, default=str)}"

    def doctor(self) -> dict[str, Any]:
        status = self.status()
        status["policy"] = {
            "identity_core_modified": False,
            "stable_memory_auto_write": False,
            "external_network_by_default": False,
            "audit_artifacts": "runs/background/YYYYMMDD-HHMMSS/",
        }
        return status

    def _task_from_row(self, row: sqlite3.Row) -> WorkerTask:
        item = self._decode(row)
        return WorkerTask(
            id=int(item["id"]),
            task_type=str(item["task_type"]),
            payload=item.get("payload_json") or {},
            priority=int(item.get("priority") or 50),
            status=str(item.get("status") or "pending"),
            safety_status=item.get("safety_status"),
            run_ref=item.get("run_ref"),
            created_at=str(item.get("created_at") or ""),
            started_at=item.get("started_at"),
            finished_at=item.get("finished_at"),
            error=item.get("error"),
            result=item.get("result_json") or {},
        )

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        for key in ("payload_json", "result_json", "summary_json", "value_json"):
            if key in item:
                try:
                    item[key] = json.loads(item.get(key) or "{}")
                except (json.JSONDecodeError, TypeError):
                    item[key] = {}
        return item

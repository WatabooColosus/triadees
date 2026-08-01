from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triade.core.config import load_config as _load_cfg_from_file
from triade.metabolism.budget import BudgetTracker
from triade.metabolism.contracts import (
    MetabolicNeed,
    ResourceUsageReceipt,
)
from triade.metabolism.health import HealthSensors
from triade.metabolism.needs import NeedsQueue
from triade.metabolism.policy import PolicyEngine
from triade.metabolism.receipts import ReceiptLedger
from triade.metabolism.recovery import RecoveryManager
from triade.metabolism.scheduler import MetabolicScheduler
from triade.metabolism.signals import SignalBus

logger = logging.getLogger(__name__)


class MetabolicCoordinator:
    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        config_path: str | Path = "triade.yml",
    ) -> None:
        self.db_path = Path(db_path)
        self.config_path = Path(config_path)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._current_cycle_id: int | None = None
        self._lock_fd: int | None = None
        self._process_lock_path = Path(
            f"/tmp/.triade_metabolism_{self.db_path.name}.lock"
        )

        self.health = HealthSensors(db_path)
        self.needs_queue = NeedsQueue(db_path)
        self.policy = PolicyEngine()
        self.budget = BudgetTracker(db_path)
        self.receipts = ReceiptLedger(db_path)
        self.recovery = RecoveryManager(db_path)
        self.signals = SignalBus(db_path)
        self.scheduler = MetabolicScheduler()

        self._mode = "observe_only"
        self._dry_run = False
        self._enabled = False
        self._status: dict[str, Any] = self._default_status()

    def _default_status(self) -> dict[str, Any]:
        return {
            "enabled": False,
            "mode": "observe_only",
            "dry_run": False,
            "cycle_count": 0,
            "current_cycle_id": None,
            "running": False,
            "last_tick_at": None,
            "last_tick_duration_ms": None,
            "last_tick_error": None,
            "status": "stopped",
        }

    # ── Process lock (PID-file based) ────────────────────────────────

    def _acquire_process_lock(self) -> str | None:
        try:
            lock_fd = os.open(
                str(self._process_lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
            os.write(lock_fd, str(os.getpid()).encode())
            os.close(lock_fd)
            self._lock_fd = lock_fd
            return None
        except FileExistsError:
            try:
                existing_pid = int(self._process_lock_path.read_text().strip())
                os.kill(existing_pid, 0)
                return "another_process_holds_lock"
            except (ValueError, ProcessLookupError, OSError):
                self._process_lock_path.unlink(missing_ok=True)
                return self._acquire_process_lock()
        except OSError as exc:
            return f"lock_acquire_failed:{exc}"

    def _release_process_lock(self) -> None:
        if self._lock_fd is not None:
            try:
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None
        try:
            self._process_lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    # ── Config ──────────────────────────────────────────────────────

    def load_config(self) -> dict[str, Any]:
        yml = _load_cfg_from_file(self.config_path)
        meta: dict[str, Any] = yml.get("metabolism") or {}
        self._enabled = bool(meta.get("enabled", False))
        self._mode = str(meta.get("mode", "observe_only"))
        self._dry_run = bool(meta.get("dry_run", False))
        interval = float(meta.get("interval_seconds", 30))
        max_cycles = int(meta.get("max_cycles", 0))
        jitter = float(meta.get("jitter_seconds", 2.0))
        thread_is_alive = bool(self._thread and self._thread.is_alive())
        if not thread_is_alive:
            self.scheduler = MetabolicScheduler(
                interval_seconds=interval, jitter_seconds=jitter, max_cycles=max_cycles
            )
        self.policy.reload(meta)
        return meta

    def configure(self, **overrides: Any) -> dict[str, Any]:
        with self._lock:
            if "enabled" in overrides:
                self._enabled = bool(overrides["enabled"])
            if "mode" in overrides:
                self._mode = str(overrides["mode"])
            if "dry_run" in overrides:
                self._dry_run = bool(overrides["dry_run"])
            if "interval_seconds" in overrides:
                self.scheduler.interval_seconds = float(overrides["interval_seconds"])
            self._status["mode"] = self._mode
            self._status["dry_run"] = self._dry_run
            return {
                "status": "configured",
                "enabled": self._enabled,
                "mode": self._mode,
                "dry_run": self._dry_run,
                "interval_seconds": self.scheduler.interval_seconds,
            }

    # ── Lifecycle ───────────────────────────────────────────────────

    def start(self) -> dict[str, Any]:
        thread_alive = bool(self._thread and self._thread.is_alive())
        if thread_alive:
            with self._lock:
                running = self._status.get("running", False)
                status_val = self._status.get("status", "stopped")
            return {
                "status": "already_running" if running else status_val,
                "enabled": self._enabled,
                "mode": self._mode,
                "dry_run": self._dry_run,
            }
        lock_error = self._acquire_process_lock()
        if lock_error:
            return {"status": "locked", "error": lock_error}
        self.load_config()
        if not self._enabled:
            self._release_process_lock()
            return {"status": "disabled", "message": "metabolism.disabled"}
        self._recover()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="metabolic-coordinator", daemon=True
        )
        self._thread.start()
        with self._lock:
            self._status["status"] = "running"
            self._status["running"] = True
        data = self._build_status_data()
        data["status"] = "started"
        return data

    def _build_status_data(self) -> dict[str, Any]:
        with self._lock:
            base = dict(self._status)
            base["enabled"] = self._enabled
            base["mode"] = self._mode
            base["dry_run"] = self._dry_run
            base["cycle_count"] = self.scheduler.cycle_count
            base["current_cycle_id"] = self._current_cycle_id
            base["thread_alive"] = bool(self._thread and self._thread.is_alive())
            return base

    def stop(self, timeout: float = 30.0) -> dict[str, Any]:
        with self._lock:
            self._stop_event.set()
            self.scheduler.request_stop()
            if self._current_cycle_id is not None:
                self._close_cycle("shutdown")
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        self._release_process_lock()
        with self._lock:
            self._status["status"] = "stopped"
            self._status["running"] = False
        return {"status": "stopped"}

    def shutdown(self) -> dict[str, Any]:
        return self.stop()

    def status(self) -> dict[str, Any]:
        with self._lock:
            self.load_config()
            base = dict(self._status)
            base["cycle_count"] = self.scheduler.cycle_count
            base["current_cycle_id"] = self._current_cycle_id
            base["enabled"] = self._enabled
            base["mode"] = self._mode
            base["dry_run"] = self._dry_run
            base["policy"] = self.policy.snapshot()
            base["scheduler"] = self.scheduler.snapshot()
            base["budget"] = self.budget.snapshot()
            base["receipt_counts"] = self.receipts.count_by_status()
            base["thread_alive"] = bool(self._thread and self._thread.is_alive())
            return base

    # ── Core cycle ─────────────────────────────────────────────────

    def tick(self) -> dict[str, Any]:
        started = time.monotonic()
        cycle_id = self._start_cycle()
        self._current_cycle_id = cycle_id

        try:
            self.signals.emit(cycle_id, "observe", "started", "beginning_observation")
            sensors = self.health.inspect()
            needs = self.needs_queue.detect(sensors, cycle_id)
            self.signals.emit(
                cycle_id,
                "observe",
                "completed",
                f"observed_{len(needs)}_needs",
                budget_used=ResourceUsageReceipt(
                    duration_ms=(time.monotonic() - started) * 1000
                ),
            )

            self.signals.emit(cycle_id, "evaluate", "started", "evaluating_needs")
            evaluated = self._evaluate(needs, cycle_id)
            self.signals.emit(
                cycle_id, "evaluate", "completed", f"evaluated_{len(evaluated)}_needs"
            )

            self.signals.emit(cycle_id, "propose", "started", "proposing_needs")
            proposed = self._propose(evaluated, cycle_id)
            self.signals.emit(
                cycle_id, "propose", "completed", f"proposed_{len(proposed)}_needs"
            )

            self.signals.emit(cycle_id, "authorize", "started", "authorizing_needs")
            authorized = self._authorize(proposed)
            self.signals.emit(
                cycle_id,
                "authorize",
                "completed",
                f"authorized_{len(authorized)}_needs",
            )

            self.signals.emit(cycle_id, "execute", "started", "executing_needs")
            executed = self._execute(authorized, cycle_id)
            self.signals.emit(
                cycle_id, "execute", "completed", f"executed_{len(executed)}_needs"
            )

            self.signals.emit(cycle_id, "verify", "started", "verifying_execution")
            verified = self._verify(executed, cycle_id)
            self.signals.emit(
                cycle_id, "verify", "completed", f"verified_{len(verified)}_needs"
            )

            self.signals.emit(cycle_id, "consolidate", "started", "consolidating")
            self._consolidate(verified, cycle_id)
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            self.signals.emit(
                cycle_id,
                "cycle",
                "failed",
                str(exc),
                budget_used=ResourceUsageReceipt(
                    duration_ms=(time.monotonic() - started) * 1000
                ),
            )
            self._close_cycle("failed", error=str(exc))
            self._current_cycle_id = None
            return {
                "status": "error",
                "cycle_id": cycle_id,
                "error": str(exc),
                "duration_ms": (time.monotonic() - started) * 1000,
            }

        self._close_cycle("completed")
        duration_ms = (time.monotonic() - started) * 1000
        self._current_cycle_id = None

        result = {
            "status": "ok",
            "cycle_id": cycle_id,
            "mode": self._mode,
            "dry_run": self._dry_run,
            "sensors_ok": sensors.get("healthy", False),
            "needs_detected": len(needs),
            "needs_evaluated": len(evaluated),
            "needs_proposed": len(proposed),
            "needs_authorized": len(authorized),
            "needs_executed": len(executed),
            "needs_verified": len(verified),
            "duration_ms": duration_ms,
        }
        with self._lock:
            self._status["last_tick_at"] = datetime.now(UTC).isoformat()
            self._status["last_tick_duration_ms"] = duration_ms
            self._status["last_tick_error"] = None
        return result

    # ── Cycle stages ────────────────────────────────────────────────

    def _evaluate(
        self, needs: list[MetabolicNeed], cycle_id: int
    ) -> list[MetabolicNeed]:
        filtered: list[MetabolicNeed] = []
        for need in needs:
            if self.needs_queue.is_on_cooldown(need):
                self.receipts.record(
                    cycle_id,
                    need.need_id,
                    "evaluate",
                    "skipped",
                    error="on_cooldown",
                )
                continue
            ok, reason = self.budget.check_cycle_budget(cycle_id, need.estimated_cost)
            if not ok:
                self.receipts.record(
                    cycle_id,
                    need.need_id,
                    "evaluate",
                    "skipped",
                    error=reason,
                )
                continue
            filtered.append(need)
        return filtered

    def _propose(
        self, needs: list[MetabolicNeed], cycle_id: int
    ) -> list[MetabolicNeed]:
        for need in needs:
            self.needs_queue.persist_need(need, cycle_id)
        return needs

    def _authorize(self, needs: list[MetabolicNeed]) -> list[MetabolicNeed]:
        authorized: list[MetabolicNeed] = []
        for need in needs:
            ok, reason = self.policy.authorize(need, self._mode)
            if ok:
                authorized.append(need)
            else:
                self.receipts.record(
                    -1, need.need_id, "authorize", "denied", error=reason
                )
        return authorized

    def _execute(
        self, needs: list[MetabolicNeed], cycle_id: int
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for need in needs:
            if self._dry_run:
                self.receipts.record(
                    cycle_id,
                    need.need_id,
                    "execute",
                    "dry_run",
                    evidence={"dry_run": True},
                )
                results.append({"need_id": need.need_id, "status": "dry_run"})
                continue
            result = self._execute_need(need, cycle_id)
            results.append(result)
        return results

    def _execute_need(self, need: MetabolicNeed, cycle_id: int) -> dict[str, Any]:
        started = time.monotonic()
        cpu_start = time.process_time()
        try:
            self._update_need_status(need.need_id, "running")
            status, detail = self._run_need_action(need, cycle_id)
            cpu_seconds = time.process_time() - cpu_start
            ram_mb = self._measure_rss_mb()
            usage = ResourceUsageReceipt(
                cpu_seconds=round(cpu_seconds, 4),
                ram_mb=round(ram_mb, 2),
                duration_ms=(time.monotonic() - started) * 1000,
            )
            if status in ("success",):
                self.receipts.record(
                    cycle_id,
                    need.need_id,
                    "execute",
                    "success",
                    budget_used=usage,
                )
                self._update_need_status(need.need_id, "completed")
            else:
                self.receipts.record(
                    cycle_id,
                    need.need_id,
                    "execute",
                    status,
                    budget_used=usage,
                    error=detail,
                )
                self._update_need_status(need.need_id, status)
            return {
                "need_id": need.need_id,
                "kind": need.kind,
                "status": status,
                "detail": detail,
                "duration_ms": usage.duration_ms,
            }
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            cpu_seconds = time.process_time() - cpu_start
            usage = ResourceUsageReceipt(
                cpu_seconds=round(cpu_seconds, 4),
                ram_mb=round(self._measure_rss_mb(), 2),
                duration_ms=(time.monotonic() - started) * 1000,
            )
            self.receipts.record(
                cycle_id,
                need.need_id,
                "execute",
                "error",
                budget_used=usage,
                error=str(exc),
            )
            self._update_need_status(need.need_id, "error")
            return {
                "need_id": need.need_id,
                "kind": need.kind,
                "status": "error",
                "detail": str(exc),
            }

    @staticmethod
    def _measure_rss_mb() -> float:
        try:
            import psutil

            return psutil.Process().memory_info().rss / (1024 * 1024)
        except (ImportError, OSError):
            return 0.0

    def _run_need_action(self, need: MetabolicNeed, cycle_id: int) -> tuple[str, str]:
        kind = need.kind
        if kind == "health_check":
            return self._action_health_check()
        elif kind == "heartbeat":
            return self._action_heartbeat()
        elif kind == "lease_supervision":
            return self._action_lease_supervision()
        elif kind == "budget_check":
            return self._action_budget_check()
        else:
            logger.warning("no_handler_for_need_kind: %s", kind)
            return ("skipped", f"no_handler:{kind}")

    def _action_health_check(self) -> tuple[str, str]:
        sensors = self.health.inspect()
        if sensors.get("healthy", False):
            return ("success", "all_sensors_healthy")
        issues = [
            k
            for k, v in sensors.items()
            if isinstance(v, dict) and not v.get("ok", True)
        ]
        return ("success", f"degraded_sensors:{','.join(issues)}")

    def _action_heartbeat(self) -> tuple[str, str]:
        try:
            from triade.runtime import LiveHeartbeat

            hb = LiveHeartbeat(self.db_path)
            result = hb.pulse()
            return ("success", f"heartbeat_pulse_cycle_{result.get('cycle', 0)}")
        except (ImportError, OSError, RuntimeError) as exc:
            return ("failure", f"heartbeat_failed:{exc}")

    def _action_lease_supervision(self) -> tuple[str, str]:
        try:
            from triade.runtime import AutonomousTaskStore

            store = AutonomousTaskStore(self.db_path)
            recovered = store.recover_expired()
            return ("success", f"released_{len(recovered)}_stale_leases")
        except (sqlite3.Error, OSError, RuntimeError) as exc:
            return ("failure", f"lease_supervision_failed:{exc}")

    def _action_budget_check(self) -> tuple[str, str]:
        try:
            from triade.runtime import ResourceLedger

            ledger = ResourceLedger(self.db_path)
            usage = ledger.daily_usage()
            over = []
            for k, used in usage.items():
                limit = float(ledger.budget.get(k, 0))
                if limit > 0 and used / limit > 0.9:
                    over.append(f"{k}_{used:.0f}/{limit:.0f}")
            status = "success"
            detail = "budgets_ok" if not over else f"near_limit:{','.join(over)}"
            return (status, detail)
        except (ImportError, OSError, RuntimeError) as exc:
            return ("failure", f"budget_check_failed:{exc}")

    def _verify(
        self, executed: list[dict[str, Any]], cycle_id: int
    ) -> list[dict[str, Any]]:
        verified: list[dict[str, Any]] = []
        for result in executed:
            if result.get("status") in ("success", "dry_run"):
                self.receipts.record(
                    cycle_id,
                    result["need_id"],
                    "verify",
                    "passed",
                    evidence={"status": result["status"]},
                )
                verified.append(result)
            else:
                self.receipts.record(
                    cycle_id,
                    result["need_id"],
                    "verify",
                    "failed",
                    error=result.get("detail", ""),
                )
                verified.append(result)
        return verified

    def _consolidate(self, verified: list[dict[str, Any]], cycle_id: int) -> None:
        passed = sum(1 for v in verified if v.get("status") in ("success", "dry_run"))
        failed = len(verified) - passed
        summary = {"passed": passed, "failed": failed, "total": len(verified)}
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                conn.execute(
                    "UPDATE metabolic_cycle SET summary_json=? WHERE cycle_id=?",
                    (json.dumps(summary), cycle_id),
                )
        except (sqlite3.Error, OSError) as exc:
            logger.warning("consolidate_update_failed: %s", exc)
        self.signals.emit(
            cycle_id,
            "consolidate",
            "completed",
            f"consolidated_{len(verified)}_results",
        )

    # ── DB helpers ──────────────────────────────────────────────────

    def _ensure_tables(self) -> None:
        migration = (
            Path(__file__).resolve().parent.parent
            / "memory/migrations/032_metabolic_core.sql"
        )
        if migration.exists():
            try:
                with sqlite3.connect(self.db_path, timeout=2) as conn:
                    conn.executescript(migration.read_text(encoding="utf-8"))
            except (sqlite3.Error, OSError) as exc:
                logger.error("migration_032_failed: %s", exc)
                raise
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                cols = {
                    str(row[1])
                    for row in conn.execute("PRAGMA table_info(metabolic_cycle)")
                }
                if "summary_json" not in cols:
                    conn.execute(
                        "ALTER TABLE metabolic_cycle ADD COLUMN summary_json TEXT DEFAULT '{}'"
                    )
        except (sqlite3.Error, OSError) as exc:
            logger.warning("summary_json_column_add_failed: %s", exc)

    def _start_cycle(self) -> int:
        self._ensure_tables()
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db_path, timeout=2) as conn:
            cur = conn.execute(
                "INSERT INTO metabolic_cycle (started_at, status, mode) VALUES (?, 'running', ?)",
                (now, self._mode),
            )
            return int(cur.lastrowid or 0)

    def _close_cycle(self, status: str, error: str | None = None) -> None:
        if self._current_cycle_id is None:
            return
        now = datetime.now(UTC).isoformat()
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                conn.execute(
                    "UPDATE metabolic_cycle SET status=?, finished_at=?, error=? WHERE cycle_id=?",
                    (status, now, error, self._current_cycle_id),
                )
        except (sqlite3.Error, OSError) as exc:
            logger.error("close_cycle_failed: %s", exc)
            raise

    def _update_need_status(self, need_id: str, status: str) -> None:
        now = datetime.now(UTC).isoformat()
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                if status in ("running",):
                    conn.execute(
                        "UPDATE metabolic_needs SET status=?, started_at=? WHERE need_id=?",
                        (status, now, need_id),
                    )
                else:
                    conn.execute(
                        "UPDATE metabolic_needs SET status=?, finished_at=?, result_json=? WHERE need_id=?",
                        (status, now, json.dumps({"final_status": status}), need_id),
                    )
        except (sqlite3.Error, OSError) as exc:
            logger.error("update_need_status_failed: %s", exc)
            raise

    def _recover(self) -> None:
        recovered = self.recovery.recover_interrupted_cycles()
        if recovered:
            self.signals.emit(
                0,
                "recovery",
                "completed",
                f"recovered_{len(recovered)}_interrupted_cycles",
            )

    def _run_loop(self) -> None:
        self._recover()
        while not self._stop_event.is_set():
            if (
                self.scheduler.max_cycles > 0
                and self.scheduler.cycle_count >= self.scheduler.max_cycles
            ):
                break
            try:
                result = self.tick()
                if result.get("status") == "error":
                    with self._lock:
                        self._status["last_tick_error"] = result.get("error")
            except Exception as exc:  # noqa: BLE001 -- one bad cycle must not kill the background loop
                logger.error("run_loop_tick_failed: %s", exc)
                with self._lock:
                    self._status["last_tick_error"] = str(exc)
                self._close_cycle("failed", error=str(exc))
                self._current_cycle_id = None
            if not self.scheduler.wait_for_next():
                break
            if self._stop_event.is_set():
                break
        self._release_process_lock()
        with self._lock:
            self._status["status"] = "stopped"
            self._status["running"] = False


# ── Module-level singleton ──────────────────────────────────────────
_COORDINATOR: MetabolicCoordinator | None = None
_COORD_LOCK = threading.Lock()


def get_coordinator(
    db_path: str | Path = "triade/memory/triade.db",
) -> MetabolicCoordinator:
    global _COORDINATOR
    with _COORD_LOCK:
        if _COORDINATOR is None:
            _COORDINATOR = MetabolicCoordinator(db_path=db_path)
        return _COORDINATOR

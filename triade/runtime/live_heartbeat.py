"""Heartbeat operacional ligero; nunca invoca modelos ni red."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import psutil  # type: ignore[import-untyped]


class LiveHeartbeat:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.started_monotonic = time.monotonic()
        self.cycle = 0
        self._ensure_table()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=2.0)
        conn.execute("PRAGMA busy_timeout=2000")
        return conn

    def _ensure_table(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS live_runtime_heartbeat (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), cycle INTEGER NOT NULL,
                wall_timestamp REAL NOT NULL, monotonic_timestamp REAL NOT NULL,
                duration_ms REAL NOT NULL, pid INTEGER NOT NULL, ram_available_mb REAL NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""
            )

    def pulse(self) -> dict[str, Any]:
        started = time.monotonic()
        memory = psutil.virtual_memory()
        self.cycle += 1
        wall = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO live_runtime_heartbeat
                (singleton,cycle,wall_timestamp,monotonic_timestamp,duration_ms,pid,ram_available_mb)
                VALUES(1,?,?,?,?,?,?) ON CONFLICT(singleton) DO UPDATE SET
                cycle=excluded.cycle,wall_timestamp=excluded.wall_timestamp,
                monotonic_timestamp=excluded.monotonic_timestamp,duration_ms=excluded.duration_ms,
                pid=excluded.pid,ram_available_mb=excluded.ram_available_mb,updated_at=CURRENT_TIMESTAMP""",
                (
                    self.cycle,
                    wall,
                    started,
                    0.0,
                    os.getpid(),
                    memory.available / 1024 / 1024,
                ),
            )
        duration_ms = (time.monotonic() - started) * 1000.0
        with self._connect() as conn:
            conn.execute(
                "UPDATE live_runtime_heartbeat SET duration_ms=? WHERE singleton=1",
                (duration_ms,),
            )
        return {
            "event": "heartbeat",
            "cycle": self.cycle,
            "duration_ms": duration_ms,
            "uptime_seconds": time.monotonic() - self.started_monotonic,
            "ram_available_mb": memory.available / 1024 / 1024,
            "llm_invocations": 0,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM live_runtime_heartbeat WHERE singleton=1"
            ).fetchone()
        if row is None:
            return {"status": "not_started"}
        payload = dict(row)
        payload["heartbeat_age_ms"] = max(
            0.0, (time.time() - float(row["wall_timestamp"])) * 1000.0
        )
        payload["status"] = (
            "healthy" if payload["heartbeat_age_ms"] < 15_000 else "stalled"
        )
        payload["llm_invocations"] = 0
        return payload

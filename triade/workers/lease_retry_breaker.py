"""Leases, reintentos y circuit breakers para workers y federación.

- Lease: lock temporal con expiración para evitar ejecución duplicada.
- Reintentos: backoff exponencial con jitter.
- Circuit Breaker: abre tras fallos consecutivos, se auto-cura.
"""

from __future__ import annotations

import json
import random
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from triade.core.contracts import utc_now

CircuitState = Literal["closed", "open", "half_open"]


@dataclass(frozen=True, slots=True)
class Lease:
    lease_id: str
    resource: str
    owner: str
    expires_at: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CircuitBreakerState:
    name: str
    state: CircuitState
    failure_count: int
    success_count: int
    last_failure_at: str | None
    opened_at: str | None
    half_open_after_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LeaseManager:
    """Gestiona leases temporales con expiración."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS leases (
                    lease_id TEXT PRIMARY KEY,
                    resource TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_leases_resource ON leases(resource, expires_at)"
            )

    def acquire(self, resource: str, owner: str, ttl_seconds: int = 60) -> Lease | None:
        self._cleanup_expired(resource)
        now = utc_now()
        from datetime import datetime, timedelta
        expires = (datetime.utcnow() + timedelta(seconds=ttl_seconds)).isoformat()
        lease_id = f"lease-{resource}-{int(time.time()*1000)}"
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO leases(lease_id, resource, owner, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
                    (lease_id, resource, owner, expires, now),
                )
            return Lease(lease_id=lease_id, resource=resource, owner=owner, expires_at=expires, created_at=now)
        except sqlite3.IntegrityError:
            return None

    def release(self, lease_id: str) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM leases WHERE lease_id = ?", (lease_id,))
        return True

    def is_acquired(self, resource: str) -> bool:
        self._cleanup_expired(resource)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM leases WHERE resource = ? AND expires_at > ?",
                (resource, utc_now()),
            ).fetchone()
        return row is not None

    def _cleanup_expired(self, resource: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM leases WHERE resource = ? AND expires_at <= ?",
                (resource, utc_now()),
            )


class RetryPolicy:
    """Backoff exponencial con jitter."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay_ms: float = 100.0,
        max_delay_ms: float = 5000.0,
        jitter: bool = True,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay_ms = base_delay_ms
        self.max_delay_ms = max_delay_ms
        self.jitter = jitter

    def delay_for_attempt(self, attempt: int) -> float:
        delay = min(self.base_delay_ms * (2 ** attempt), self.max_delay_ms)
        if self.jitter:
            delay = delay * (0.5 + random.random() * 0.5)
        return delay

    def should_retry(self, attempt: int) -> bool:
        return attempt < self.max_retries


class CircuitBreaker:
    """Circuit breaker con estados closed/open/half_open."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 60.0,
        success_threshold: int = 2,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout_seconds
        self.success_threshold = success_threshold
        self._state: CircuitState = "closed"
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_at: str | None = None
        self._opened_at: str | None = None

    @property
    def state(self) -> CircuitState:
        if self._state == "open" and self._opened_at:
            from datetime import datetime, timezone
            opened = datetime.fromisoformat(self._opened_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if (now - opened).total_seconds() > self.recovery_timeout:
                self._state = "half_open"
                self._success_count = 0
        return self._state

    def allow_request(self) -> bool:
        s = self.state
        if s == "closed":
            return True
        if s == "half_open":
            return True
        return False

    def record_success(self) -> None:
        if self._state == "half_open":
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                self._state = "closed"
                self._failure_count = 0
                self._success_count = 0
                self._opened_at = None
        elif self._state == "closed":
            self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_at = utc_now()
        if self._failure_count >= self.failure_threshold:
            self._state = "open"
            self._opened_at = utc_now()

    def reset(self) -> None:
        self._state = "closed"
        self._failure_count = 0
        self._success_count = 0
        self._opened_at = None

    def to_dict(self) -> dict[str, Any]:
        return CircuitBreakerState(
            name=self.name,
            state=self.state,
            failure_count=self._failure_count,
            success_count=self._success_count,
            last_failure_at=self._last_failure_at,
            opened_at=self._opened_at,
            half_open_after_seconds=self.recovery_timeout,
        ).to_dict()

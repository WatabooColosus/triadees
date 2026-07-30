"""Usuarios, sesiones, RBAC, rate limits y validación para exposición pública."""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from triade.security.distributed_auth import RedisPublicAuthBackend

SCHEMA = Path(__file__).resolve().parent.parent / "memory/schemas.sql"
MIGRATION = (
    Path(__file__).resolve().parent.parent / "memory/migrations/030_public_security.sql"
)
Role = Literal["viewer", "operator", "admin"]
ROLE_LEVEL = {"viewer": 1, "operator": 2, "admin": 3}
INJECTION_MARKERS = (
    "ignore previous instructions",
    "reveal system prompt",
    "exfiltrate",
    "bypass policy",
)


class PublicAuthStore:
    def __init__(
        self,
        db_path: str | Path,
        *,
        session_ttl_seconds: int = 3600,
        rate_limit_per_minute: int = 60,
        max_failed_attempts: int = 5,
        lockout_seconds: int = 300,
        redis_url: str | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.session_ttl_seconds = session_ttl_seconds
        self.rate_limit_per_minute = rate_limit_per_minute
        self.max_failed_attempts = max_failed_attempts
        self.lockout_seconds = lockout_seconds
        configured_redis = (
            redis_url if redis_url is not None else os.getenv("TRIADE_REDIS_URL")
        )
        self.distributed = (
            RedisPublicAuthBackend(configured_redis) if configured_redis else None
        )
        self.hasher = PasswordHasher()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA.read_text(encoding="utf-8"))
            conn.executescript(MIGRATION.read_text(encoding="utf-8"))

    def create_user(
        self, username: str, password: str, role: Role, tenant_id: str
    ) -> dict[str, str]:
        if len(password) < 12 or not username.strip() or not tenant_id.strip():
            raise ValueError("strong_password_username_and_tenant_required")
        user_id = f"usr-{uuid.uuid4().hex}"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO auth_users VALUES (?, ?, ?, ?, ?, 0, 0, NULL, ?)",
                (
                    user_id,
                    username,
                    self.hasher.hash(password),
                    role,
                    tenant_id,
                    datetime.now(UTC).isoformat(),
                ),
            )
        return {
            "user_id": user_id,
            "username": username,
            "role": role,
            "tenant_id": tenant_id,
        }

    def authenticate(self, username: str, password: str) -> dict[str, Any]:
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM auth_users WHERE username=?", (username,)
            ).fetchone()
            if row is None or row["disabled"]:
                self._audit(
                    conn, username, None, "login", "denied", "unknown_or_disabled"
                )
                raise PermissionError("invalid_credentials")
            if row["locked_until"] and float(row["locked_until"]) > now:
                self._audit(
                    conn, row["user_id"], row["tenant_id"], "login", "denied", "locked"
                )
                raise PermissionError("account_locked")
            try:
                self.hasher.verify(row["password_hash"], password)
            except VerifyMismatchError as exc:
                attempts = int(row["failed_attempts"]) + 1
                locked_until = (
                    now + self.lockout_seconds
                    if attempts >= self.max_failed_attempts
                    else None
                )
                conn.execute(
                    "UPDATE auth_users SET failed_attempts=?,locked_until=? WHERE user_id=?",
                    (attempts, locked_until, row["user_id"]),
                )
                self._audit(
                    conn,
                    row["user_id"],
                    row["tenant_id"],
                    "login",
                    "denied",
                    "bad_password",
                )
                conn.commit()
                raise PermissionError("invalid_credentials") from exc
            conn.execute(
                "UPDATE auth_users SET failed_attempts=0,locked_until=NULL WHERE user_id=?",
                (row["user_id"],),
            )
            token = secrets.token_urlsafe(48)
            session_id = f"ses-{uuid.uuid4().hex}"
            expires_at = now + self.session_ttl_seconds
            conn.execute(
                "INSERT INTO auth_sessions VALUES (?, ?, ?, ?, NULL, ?)",
                (
                    session_id,
                    self._hash(token),
                    row["user_id"],
                    expires_at,
                    datetime.now(UTC).isoformat(),
                ),
            )
            self._audit(
                conn, row["user_id"], row["tenant_id"], "login", "allowed", session_id
            )
        result = {
            "access_token": token,
            "token_type": "bearer",
            "expires_at": expires_at,
            "session_id": session_id,
            "user_id": row["user_id"],
            "role": row["role"],
            "tenant_id": row["tenant_id"],
        }
        if self.distributed is not None:
            self.distributed.register_session(
                self._hash(token), result, ttl_seconds=self.session_ttl_seconds
            )
        return result

    def authorize(
        self, token: str, *, required_role: Role = "viewer"
    ) -> dict[str, Any]:
        now = time.time()
        token_hash = self._hash(token)
        if self.distributed is not None:
            if self.distributed.is_revoked(token_hash):
                raise PermissionError("session_invalid_expired_or_revoked")
            principal = self.distributed.get_session(token_hash)
            if principal is None or float(principal.get("expires_at") or 0) <= now:
                raise PermissionError("session_invalid_expired_or_revoked")
            role = str(principal.get("role") or "")
            if role not in ROLE_LEVEL or ROLE_LEVEL[role] < ROLE_LEVEL[required_role]:
                raise PermissionError("insufficient_role")
            user_id = str(principal.get("user_id") or "")
            if not self.distributed.consume_rate(
                user_id, limit=self.rate_limit_per_minute, now=now
            ):
                raise RuntimeError("rate_limit_exceeded")
            return {
                "session_id": principal.get("session_id"),
                "user_id": user_id,
                "role": role,
                "tenant_id": principal.get("tenant_id"),
            }
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT s.session_id,s.expires_at,s.revoked_at,u.user_id,u.role,u.tenant_id,u.disabled
                FROM auth_sessions s JOIN auth_users u ON u.user_id=s.user_id WHERE s.token_hash=?""",
                (token_hash,),
            ).fetchone()
            if (
                row is None
                or row["revoked_at"]
                or row["disabled"]
                or float(row["expires_at"]) <= now
            ):
                raise PermissionError("session_invalid_expired_or_revoked")
            if ROLE_LEVEL[str(row["role"])] < ROLE_LEVEL[required_role]:
                self._audit(
                    conn,
                    row["user_id"],
                    row["tenant_id"],
                    "authorize",
                    "denied",
                    required_role,
                )
                raise PermissionError("insufficient_role")
            window = int(now // 60)
            count = conn.execute(
                "SELECT COUNT(*) FROM auth_rate_events WHERE user_id=? AND created_at>=?",
                (row["user_id"], now - 60.0),
            ).fetchone()[0]
            if count >= self.rate_limit_per_minute:
                raise RuntimeError("rate_limit_exceeded")
            conn.execute(
                "INSERT INTO auth_rate_events(user_id,window_key,created_at) VALUES (?,?,?)",
                (row["user_id"], window, now),
            )
        return {
            "session_id": row["session_id"],
            "user_id": row["user_id"],
            "role": row["role"],
            "tenant_id": row["tenant_id"],
        }

    def revoke(self, token: str, *, actor: str) -> bool:
        token_hash = self._hash(token)
        distributed_revoked = False
        if self.distributed is not None:
            distributed_revoked = self.distributed.revoke(
                token_hash, ttl_seconds=self.session_ttl_seconds
            )
        with sqlite3.connect(self.db_path) as conn:
            changed = conn.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                (time.time(), token_hash),
            ).rowcount
            self._audit(
                conn,
                actor,
                None,
                "session_revoke",
                "allowed" if changed else "not_found",
                "token_hash_only",
            )
        return changed == 1 or distributed_revoked

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def _audit(
        conn: sqlite3.Connection,
        actor: str,
        tenant_id: str | None,
        action: str,
        outcome: str,
        detail: str,
    ) -> None:
        conn.execute(
            "INSERT INTO auth_audit(actor,tenant_id,action,outcome,detail,created_at) VALUES (?,?,?,?,?,?)",
            (actor, tenant_id, action, outcome, detail, datetime.now(UTC).isoformat()),
        )


def validate_tool_input(payload: dict[str, Any]) -> None:
    serialized = str(payload).lower()
    if any(marker in serialized for marker in INJECTION_MARKERS):
        raise ValueError("prompt_injection_marker_blocked")
    if len(serialized) > 100_000:
        raise ValueError("tool_input_too_large")


def enforce_egress(url: str, allowed_hosts: set[str]) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname not in allowed_hosts
    ):
        raise PermissionError("network_egress_denied")

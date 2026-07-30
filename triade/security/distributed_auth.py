"""Estado distribuido de sesiones, revocaciones y cuotas públicas en Redis."""

from __future__ import annotations

import json
import uuid
from typing import Any


class DistributedAuthUnavailable(RuntimeError):
    pass


class RedisPublicAuthBackend:
    def __init__(self, url: str, *, namespace: str = "triade:public-auth") -> None:
        if not url.strip():
            raise ValueError("redis_url_required")
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError("redis_dependency_unavailable") from exc
        self._redis_error: Any = redis.exceptions.RedisError
        self.client: Any = redis.Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
        )
        try:
            self.client.ping()
        except self._redis_error as exc:
            raise DistributedAuthUnavailable("redis_backend_unavailable") from exc
        self.namespace = namespace.strip(":")

    def _key(self, kind: str, identifier: str) -> str:
        return f"{self.namespace}:{kind}:{identifier}"

    def register_session(
        self, token_hash: str, payload: dict[str, Any], *, ttl_seconds: int
    ) -> None:
        try:
            self.client.set(
                self._key("session", token_hash),
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ex=max(1, int(ttl_seconds)),
            )
        except self._redis_error as exc:
            raise DistributedAuthUnavailable("redis_backend_unavailable") from exc

    def get_session(self, token_hash: str) -> dict[str, Any] | None:
        try:
            raw = self.client.get(self._key("session", token_hash))
        except self._redis_error as exc:
            raise DistributedAuthUnavailable("redis_backend_unavailable") from exc
        if not raw:
            return None
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else None

    def revoke(self, token_hash: str, *, ttl_seconds: int) -> bool:
        pipeline = self.client.pipeline(transaction=True)
        pipeline.set(self._key("revoked", token_hash), "1", ex=max(1, int(ttl_seconds)))
        pipeline.delete(self._key("session", token_hash))
        try:
            results = pipeline.execute()
        except self._redis_error as exc:
            raise DistributedAuthUnavailable("redis_backend_unavailable") from exc
        return bool(results and results[0])

    def is_revoked(self, token_hash: str) -> bool:
        try:
            return bool(self.client.exists(self._key("revoked", token_hash)))
        except self._redis_error as exc:
            raise DistributedAuthUnavailable("redis_backend_unavailable") from exc

    def consume_rate(self, user_id: str, *, limit: int, now: float) -> bool:
        key = self._key("rate", user_id)
        member = f"{now:.9f}:{uuid.uuid4().hex}"
        script = """
        redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
        local count = redis.call('ZCARD', KEYS[1])
        if count >= tonumber(ARGV[2]) then return 0 end
        redis.call('ZADD', KEYS[1], ARGV[3], ARGV[4])
        redis.call('EXPIRE', KEYS[1], 61)
        return 1
        """
        try:
            accepted = self.client.eval(
                script,
                1,
                key,
                now - 60.0,
                max(1, int(limit)),
                now,
                member,
            )
        except self._redis_error as exc:
            raise DistributedAuthUnavailable("redis_backend_unavailable") from exc
        return bool(accepted)

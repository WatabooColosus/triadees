"""Identidad contextual obligatoria para memoria y estado longitudinal."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")


@dataclass(frozen=True, slots=True)
class PrincipalScope:
    tenant_id: str
    user_id: str
    session_id: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not _SAFE_ID.fullmatch(value):
                raise ValueError(f"{name} inválido; use 1-128 caracteres seguros")

    @property
    def principal_id(self) -> str:
        return f"{self.tenant_id}:{self.user_id}"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_context(cls, context: dict[str, Any] | None, *, source: str = "local") -> "PrincipalScope":
        context = context or {}
        if not any(context.get(key) for key in ("tenant_id", "user_id", "principal_id", "session_id")) and source in {"console", "test"}:
            return cls("legacy", "legacy", "legacy")
        tenant = str(context.get("tenant_id") or "local").strip()
        user = str(context.get("user_id") or context.get("principal_id") or f"anonymous:{source}").strip()
        session = str(context.get("session_id") or f"default:{user}").strip()
        return cls(tenant_id=tenant, user_id=user, session_id=session)

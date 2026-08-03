"""Validated active memory for Triade Omega.

Loads the portable ethical covenant, operational permissions and architecture
intent used to seed runtime context. The JSON document is data; this module is
the governed loader and policy boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final


SUPPORTED_SCHEMA_VERSIONS: Final[frozenset[str]] = frozenset({"1.0.0"})
DEFAULT_ACTIVE_MEMORY_PATH: Final[Path] = (
    Path(__file__).resolve().parents[1] / "memory" / "active_memory.json"
)


class ActiveMemoryError(RuntimeError):
    """Raised when active memory cannot be trusted or loaded safely."""


@dataclass(frozen=True, slots=True)
class ActiveMemorySnapshot:
    """Immutable, checksum-addressed snapshot of active memory."""

    payload: dict[str, Any]
    source: Path
    checksum: str

    @property
    def schema_version(self) -> str:
        return str(self.payload["schema_version"])

    @property
    def memory_id(self) -> str:
        return str(self.payload["memory_id"])

    @property
    def permissions(self) -> dict[str, bool]:
        raw = self.payload["operational_permissions"]
        return {str(key): bool(value) for key, value in raw.items()}

    def permits(self, capability: str) -> bool:
        """Return an explicit permission; unknown capabilities fail closed."""

        return self.permissions.get(capability, False)

    def runtime_context(self) -> dict[str, Any]:
        """Return the bounded context intended for runtime injection."""

        return {
            "memory_id": self.memory_id,
            "schema_version": self.schema_version,
            "checksum": self.checksum,
            "provenance": self.payload["provenance"],
            "ethical_covenant": self.payload["ethical_covenant"],
            "operational_permissions": self.permissions,
            "permission_rules": self.payload["permission_rules"],
            "architecture_direction": self.payload["architecture_direction"],
            "runtime_invariants": self.payload["runtime_invariants"],
        }


def _canonical_checksum(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ActiveMemoryError("Active memory root must be a JSON object.")

    required = {
        "schema_version",
        "memory_id",
        "status",
        "provenance",
        "ethical_covenant",
        "operational_permissions",
        "permission_rules",
        "architecture_direction",
        "runtime_invariants",
        "activation",
    }
    missing = sorted(required.difference(payload))
    if missing:
        raise ActiveMemoryError(
            f"Active memory is missing required keys: {', '.join(missing)}"
        )

    schema_version = str(payload["schema_version"])
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ActiveMemoryError(
            f"Unsupported active memory schema: {schema_version}"
        )

    if payload["status"] != "active":
        raise ActiveMemoryError("Active memory document is not active.")

    permissions = payload["operational_permissions"]
    if not isinstance(permissions, dict) or not permissions:
        raise ActiveMemoryError("Operational permissions must be a non-empty object.")
    if not all(isinstance(value, bool) for value in permissions.values()):
        raise ActiveMemoryError("Every operational permission must be boolean.")

    forbidden_autonomy = {
        "activate_lora_in_production",
        "modify_identity_core",
        "execute_irreversible_actions",
        "override_human_consent",
        "self_expand_permissions",
    }
    unsafe = sorted(name for name in forbidden_autonomy if permissions.get(name))
    if unsafe:
        raise ActiveMemoryError(
            "Unsafe foundational permissions cannot be enabled in active memory: "
            + ", ".join(unsafe)
        )

    invariants = payload["runtime_invariants"]
    if not isinstance(invariants, list) or not invariants:
        raise ActiveMemoryError("Runtime invariants must be a non-empty list.")

    return payload


def resolve_active_memory_path(path: str | Path | None = None) -> Path:
    """Resolve explicit path, governed environment override or repository default."""

    if path is not None:
        return Path(path).expanduser().resolve()
    override = os.getenv("TRIADE_ACTIVE_MEMORY_PATH")
    if override:
        return Path(override).expanduser().resolve()
    return DEFAULT_ACTIVE_MEMORY_PATH


def load_active_memory(path: str | Path | None = None) -> ActiveMemorySnapshot:
    """Load and validate active memory, failing closed on malformed data."""

    source = resolve_active_memory_path(path)
    try:
        raw = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ActiveMemoryError(f"Cannot read active memory at {source}: {exc}") from exc

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ActiveMemoryError(
            f"Invalid JSON in active memory at {source}: {exc}"
        ) from exc

    payload = _validate(decoded)
    return ActiveMemorySnapshot(
        payload=payload,
        source=source,
        checksum=_canonical_checksum(payload),
    )


GLOBAL_ACTIVE_MEMORY = load_active_memory()

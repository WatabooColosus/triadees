"""Observabilidad compacta del Capability Registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .registry import CapabilityRegistry


class CapabilityObservability:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.registry = CapabilityRegistry(db_path)

    def snapshot(self) -> dict[str, Any]:
        items = self.registry.list()
        by_state: dict[str, int] = {}
        by_domain: dict[str, int] = {}
        critical = 0
        deprecated = 0
        blocked = 0
        for item in items:
            state = str(item.get("state") or "unknown")
            domain = str(item.get("domain") or "unknown")
            by_state[state] = by_state.get(state, 0) + 1
            by_domain[domain] = by_domain.get(domain, 0) + 1
            critical += int(bool(item.get("critical")))
            deprecated += int(state == "deprecated")
            blocked += int(state == "blocked")
        status = "empty" if not items else "ok"
        if blocked:
            status = "attention"
        return {
            "status": status,
            "total": len(items),
            "critical": critical,
            "blocked": blocked,
            "deprecated": deprecated,
            "by_state": by_state,
            "by_domain": by_domain,
            "capabilities": items,
        }

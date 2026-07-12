"""Exportación JSON determinista y verificable del Capability Registry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .registry import CapabilityRegistry


class CapabilityRegistryExporter:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.registry = CapabilityRegistry(db_path)

    def build(self) -> dict[str, Any]:
        capabilities = self.registry.list()
        history = {
            item["capability_id"]: self.registry.history(item["capability_id"])
            for item in capabilities
        }
        payload = {
            "schema_version": "1.0.0",
            "capabilities": capabilities,
            "history": history,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return {
            **payload,
            "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        }

    def write(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(self.build(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return output

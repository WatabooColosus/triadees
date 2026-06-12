"""Reportes legibles para QualiaBus."""

from __future__ import annotations

from typing import Any

from .store import QualiaStore


def build_qualia_report(store: QualiaStore, run_id: str | None = None, limit: int = 20) -> dict[str, Any]:
    counts = store.counts(run_id=run_id)
    latest_state = store.latest_state(run_id=run_id)
    status = "empty" if not any(counts.values()) else "ok"
    return {
        "status": status,
        "run_id": run_id,
        "counts": counts,
        "latest_state": latest_state,
        "experiences": store.list_experiences(run_id=run_id, limit=limit),
        "signals": store.list_signals(run_id=run_id, limit=limit),
        "central_packets": store.list_central_packets(run_id=run_id, limit=limit),
        "storage_packets": store.list_storage_packets(run_id=run_id, limit=limit),
    }

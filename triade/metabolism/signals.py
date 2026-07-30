from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from triade.metabolism.contracts import MetabolicSignal, ResourceUsageReceipt


class SignalBus:
    def __init__(self, db_path: str = "triade/memory/triade.db") -> None:
        self.db_path = db_path
        self._signals: list[MetabolicSignal] = []

    def emit(
        self,
        cycle: int,
        stage: str,
        status: str,
        reason: str = "",
        need_id: str | None = None,
        budget_used: ResourceUsageReceipt | None = None,
    ) -> MetabolicSignal:
        signal = MetabolicSignal(
            signal_id=f"sig-{uuid.uuid4().hex[:12]}",
            cycle=cycle,
            stage=stage,
            need_id=need_id,
            status=status,
            reason=reason,
            timestamp=datetime.now(UTC).isoformat(),
            budget_used=budget_used,
        )
        self._signals.append(signal)
        self._persist(signal)
        return signal

    def _persist(self, signal: MetabolicSignal) -> None:
        try:
            import sqlite3

            with sqlite3.connect(self.db_path, timeout=2) as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO metabolic_signals
                    (signal_id, cycle_id, stage, need_id, signal_status, reason, timestamp, budget_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        signal.signal_id,
                        signal.cycle,
                        signal.stage,
                        signal.need_id,
                        signal.status,
                        signal.reason,
                        signal.timestamp,
                        json.dumps(signal.budget_used.to_dict() if signal.budget_used else {}),
                    ),
                )
        except (ImportError, OSError, RuntimeError):
            pass

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._signals[-limit:]]

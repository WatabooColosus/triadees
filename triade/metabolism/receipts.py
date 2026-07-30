from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triade.metabolism.contracts import MetabolicReceipt, ResourceUsageReceipt

logger = logging.getLogger(__name__)


class ReceiptLedger:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def record(
        self,
        cycle: int,
        need_id: str,
        stage: str,
        status: str,
        *,
        budget_used: ResourceUsageReceipt | None = None,
        artifact_ref: str | None = None,
        effect_receipt_ref: str | None = None,
        error: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> MetabolicReceipt:
        now = datetime.now(UTC)
        receipt = MetabolicReceipt(
            receipt_id=f"mrec-{uuid.uuid4().hex[:12]}",
            cycle=cycle,
            need_id=need_id,
            stage=stage,
            status=status,
            started_at=now.isoformat(),
            finished_at=now.isoformat(),
            budget_used=budget_used or ResourceUsageReceipt(),
            artifact_ref=artifact_ref,
            effect_receipt_ref=effect_receipt_ref,
            error=error,
            evidence=evidence or {},
        )
        self._persist(receipt)
        return receipt

    def _persist(self, receipt: MetabolicReceipt) -> None:
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO metabolic_receipts
                    (receipt_id, cycle_id, need_id, stage, status,
                     started_at, finished_at,
                     cpu_seconds, ram_mb, duration_ms,
                     artifact_ref, effect_receipt_ref, error, evidence_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        receipt.receipt_id,
                        receipt.cycle,
                        receipt.need_id,
                        receipt.stage,
                        receipt.status,
                        receipt.started_at,
                        receipt.finished_at,
                        receipt.budget_used.cpu_seconds,
                        receipt.budget_used.ram_mb,
                        receipt.budget_used.duration_ms,
                        receipt.artifact_ref,
                        receipt.effect_receipt_ref,
                        receipt.error,
                        json.dumps(receipt.evidence),
                    ),
                )
        except (sqlite3.Error, OSError) as exc:
            logger.warning("receipt_persist_failed: %s", exc)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT * FROM metabolic_receipts
                    ORDER BY started_at DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
                return [dict(r) for r in rows]
        except (sqlite3.Error, OSError) as exc:
            logger.warning("receipt_query_failed: %s", exc)
            return []

    def count_by_status(self) -> dict[str, int]:
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                rows = conn.execute(
                    "SELECT status, COUNT(*) as cnt FROM metabolic_receipts GROUP BY status"
                ).fetchall()
                return {str(r[0]): int(r[1]) for r in rows}
        except (sqlite3.Error, OSError) as exc:
            logger.warning("count_by_status_failed: %s", exc)
            return {}

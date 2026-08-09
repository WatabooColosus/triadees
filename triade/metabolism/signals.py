from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triade.metabolism.contracts import MetabolicSignal, ResourceUsageReceipt

logger = logging.getLogger(__name__)


class SignalBus:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
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
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                # `cycle_id = 0` es el centinela de "emitido fuera de un ciclo
                # metabólico": lo usa el gobernador de workers, que decide modo
                # de trabajo sin pertenecer a ningún ciclo. Pero el 0 nunca se
                # declaró en `metabolic_cycle`, así que cada una de esas señales
                # quedaba huérfana de su clave foránea —142 el 2026-08-09—.
                #
                # Se declara aquí, en el escritor, y no como migración: no hay
                # runner que aplique los `.sql` sobre la base viva, así que una
                # migración dejaría el arreglo sin efecto donde importa.
                if signal.cycle == 0:
                    conn.execute(
                        """INSERT OR IGNORE INTO metabolic_cycle
                        (cycle_id, started_at, finished_at, status, mode, summary_json)
                        VALUES (0, ?, ?, 'out_of_cycle', 'none', ?)""",
                        (
                            signal.timestamp,
                            signal.timestamp,
                            json.dumps(
                                {
                                    "nota": (
                                        "centinela: señales emitidas fuera de un "
                                        "ciclo metabólico, como las del "
                                        "gobernador de workers"
                                    )
                                },
                                ensure_ascii=False,
                            ),
                        ),
                    )
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
                        json.dumps(
                            signal.budget_used.to_dict() if signal.budget_used else {}
                        ),
                    ),
                )
        except (ImportError, OSError, RuntimeError, sqlite3.Error) as exc:
            # `sqlite3.Error` faltaba y no hereda de las otras tres: un fallo de
            # base aquí escapaba de este `try` y tumbaba al emisor, que sólo
            # quería dejar constancia de una señal.
            logger.warning("signal_persist_failed: %s", exc)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._signals[-limit:]]

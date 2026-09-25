"""Aprobación de propuestas con confianza finita >= 0,96 (96%).

Planner y worker comparten este gate. El entorno puede elevar el umbral,
pero no reducir el mínimo autorizado el 2026-09-21. Aprobar una propuesta
permite investigarla y evaluarla; no certifica estabilidad ni cambia el
gate independiente de promoción estable.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Any

from triade.db import sqlite3

#: Mínimo autorizado el 2026-09-21: 0,96 en escala 0–1 (96%).
DEFAULT_MIN_CONFIDENCE = 0.96

#: Quién figura como aprobador cuando decide la política.
#:
#: El responsable autorizó el 2026-08-11 que estas aprobaciones queden
#: certificadas a su nombre. Su nombre se estampa —con
#: `TRIADE_SELF_IMPROVEMENT_POLICY_AUTHORIZER`— pero **detrás del prefijo
#: `auto:`**, no en su lugar. La autorización es real y permanente; la
#: aprobación concreta la tomó la política, y quien audite esto dentro de un año
#: tiene que poder distinguir las dos cosas sin leer el código. Una firma humana
#: indistinguible de una automática no protege al que firma: le atribuye
#: decisiones que no miró.
POLICY_APPROVER = "auto:threshold_policy"


def policy_approver() -> str:
    """Aprobador a registrar, con la autorización permanente si está declarada."""
    authorizer = os.getenv("TRIADE_SELF_IMPROVEMENT_POLICY_AUTHORIZER", "").strip()
    if not authorizer:
        return POLICY_APPROVER
    return f"{POLICY_APPROVER} (autorizado por {authorizer})"


@dataclass(frozen=True, slots=True)
class AutoApprovalDecision:
    allowed: bool
    reason: str
    confidence: float | None = None
    threshold: float = DEFAULT_MIN_CONFIDENCE

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "confidence": self.confidence,
            "threshold": self.threshold,
        }


def policy_enabled() -> bool:
    """¿Está encendida la aprobación por política?"""
    return os.getenv(
        "TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE", "1"
    ).strip().lower() not in {
        "0",
        "false",
        "no",
    }


def min_confidence() -> float:
    """Umbral vigente. Un valor ilegible no baja el listón: se usa el defecto."""
    raw = os.getenv("TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE_MIN_CONFIDENCE", "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_MIN_CONFIDENCE
    if not 0.0 <= value <= 1.0:
        return DEFAULT_MIN_CONFIDENCE
    return max(DEFAULT_MIN_CONFIDENCE, value)


def _loads(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def evaluate(
    proposal_payload: dict[str, Any], signal_payload: dict[str, Any]
) -> AutoApprovalDecision:
    """Decide sobre una propuesta ya cargada. Sin tocar la base."""
    threshold = min_confidence()

    if not policy_enabled():
        return AutoApprovalDecision(
            False, "la aprobación por política está apagada", None, threshold
        )

    raw_confidence: Any = signal_payload.get("confidence")
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError):
        return AutoApprovalDecision(
            False, "la señal no declara confianza medible", None, threshold
        )

    if (
        isinstance(raw_confidence, bool)
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        return AutoApprovalDecision(
            False, "la confianza debe ser finita y estar entre 0 y 1", None, threshold
        )

    if confidence < threshold:
        return AutoApprovalDecision(
            False,
            f"confianza {confidence:.2f} por debajo del umbral {threshold:.2f}",
            confidence,
            threshold,
        )

    return AutoApprovalDecision(
        True,
        f"confianza {confidence:.2f} alcanza el umbral {threshold:.2f}",
        confidence,
        threshold,
    )


def decide_for_proposal(
    conn: sqlite3.Connection, proposal_id: str
) -> AutoApprovalDecision:
    """Igual que `evaluate`, cargando propuesta y señal de la base."""
    threshold = min_confidence()
    row = conn.execute(
        "SELECT payload_json, signal_id FROM improvement_proposals WHERE proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    if row is None:
        return AutoApprovalDecision(False, "propuesta no registrada", None, threshold)

    proposal_payload = _loads(row["payload_json"])
    signal_row = conn.execute(
        "SELECT payload_json FROM improvement_signals WHERE signal_id = ?",
        (row["signal_id"],),
    ).fetchone()
    signal_payload = _loads(signal_row["payload_json"]) if signal_row else {}
    return evaluate(proposal_payload, signal_payload)


def auto_approvable_open_proposals(conn: sqlite3.Connection) -> list[str]:
    """Propuestas abiertas que la política aprobaría ahora mismo.

    Es lo que el planificador necesita para decidir si hay trabajo: encolar la
    evaluación porque existe una propuesta abierta que *no* se va a poder
    aprobar sería girar en vacío, que es el fallo contrario al que se arregla.
    """
    try:
        rows = conn.execute(
            "SELECT proposal_id FROM improvement_proposals WHERE status = 'open' "
            "ORDER BY rowid ASC"
        ).fetchall()
    except sqlite3.Error:
        return []
    return [
        str(row["proposal_id"])
        for row in rows
        if decide_for_proposal(conn, str(row["proposal_id"])).allowed
    ]

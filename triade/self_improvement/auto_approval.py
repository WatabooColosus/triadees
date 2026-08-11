"""Cuándo puede la política aprobar una propuesta sin firma humana.

Existe por dos motivos, y el primero es un fallo de circuito real.

**El circuito estaba muerto.** `MissionPlanner._plan_self_improvement` sólo
encolaba `self_improvement_evaluation` si ya había propuestas en `approved`, y
lo único capaz de aprobar sin humano —la política de auto-aprobación— vive
*dentro* de ese mismo handler. Una propuesta `open` no podía llegar a
`approved` por sí sola: el código de auto-aprobación era inalcanzable salvo que
una persona aprobara antes a mano, que es justo lo que la política venía a
evitar. Medido el 2026-08-10: `improvement_proposals`, `improvement_canaries`,
`improvement_candidate_links`, `neuron_candidates` y
`improvement_canary_observations`, todas a cero. No era falta de código: era una
cadena que no podía empezar.

**Y no había umbral.** La política aprobaba la primera propuesta abierta que
encontrara, sin mirar la calidad de la señal que la origina. El responsable
autorizó el 2026-08-11 que Tríade apruebe sola **sólo por encima de 0.9**, así
que el listón se pone aquí y en un único sitio: si planner y worker decidieran
por su cuenta, se desincronizarían y volveríamos a tener una cadena que empieza
y no puede seguir.

Dos condiciones, y las dos tienen que darse:

1. la política está encendida (`TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE`);
2. la confianza de la señal llega al umbral.

Se mira la **confianza** y no el impacto a propósito. El impacto dice cuánto se
ganaría si la hipótesis fuera cierta; la confianza dice cuánto sabemos que lo
es. Aprobar sola una hipótesis de impacto alto y confianza baja es exactamente
lo que un umbral debe impedir.

**Por qué `requires_human_approval` no bloquea aquí.** Es tentador usarlo como
tercer candado, y sería un error: ese campo lo exige el store al *crear* una
propuesta de riesgo alto, no al aprobarla, y el gate duro se movió a
`stable_promotion_gate` —el paso experimental → estable, que es el
irreversible— precisamente porque exigir una firma para *proponer* dejaba el
circuito inerte esperando a alguien y convertía la aprobación en un trámite que
se firma sin mirar. Bloquear aquí devolvería el circuito a cero justo para el
caso que existe en producción: la única señal viva es de riesgo alto.

Aprobar abre la puerta a investigar, construir una candidata y medirla en
sandbox. Nada de eso cambia el organismo. Lo que sí lo cambia sigue pidiendo
permiso.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from typing import Any

#: Umbral por defecto. El responsable lo autorizó en 0.9 el 2026-08-11 y lo
#: subió a 0.94 el mismo día.
DEFAULT_MIN_CONFIDENCE = 0.94

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
    return value


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

"""Rollback obligatorio — enforcement del Artículo III de la Constitución.

Toda capacidad crítica debe tener rollback registrado antes de promover.
Esta capa bloquea promociones sin rollback y audita la integridad.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now


@dataclass(frozen=True, slots=True)
class MandatoryRollbackCheck:
    capability_id: str
    has_rollback_handler: bool
    has_stable_baseline: bool
    rollback_policy: str | None
    promotion_allowed: bool
    blocking_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "has_rollback_handler": self.has_rollback_handler,
            "has_stable_baseline": self.has_stable_baseline,
            "rollback_policy": self.rollback_policy,
            "promotion_allowed": self.promotion_allowed,
            "blocking_reasons": list(self.blocking_reasons),
        }


class MandatoryRollbackEnforcer:
    """Verifica que toda capacidad crítica tenga rollback antes de promover."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def check_promotion(
        self,
        capability_id: str,
        *,
        registered_handlers: set[str] | None = None,
    ) -> MandatoryRollbackCheck:
        handlers = registered_handlers or set()
        has_handler = capability_id in handlers
        has_baseline = self._has_stable_baseline(capability_id)
        rollback_policy = self._get_rollback_policy(capability_id)
        blocking: list[str] = []

        if not has_handler:
            blocking.append(f"No hay rollback handler registrado para '{capability_id}'.")
        if not has_baseline:
            blocking.append(f"No hay baseline estable registrado para '{capability_id}'.")
        if not rollback_policy:
            blocking.append(f"La capacidad '{capability_id}' no tiene rollback_policy definida.")

        is_critical = self._is_critical(capability_id)
        promotion_allowed = not is_critical or (has_handler and has_baseline and rollback_policy)

        if is_critical and not promotion_allowed:
            blocking.insert(0, f"Capacidad CRÍTICA '{capability_id}' requiere rollback completo para promover.")

        return MandatoryRollbackCheck(
            capability_id=capability_id,
            has_rollback_handler=has_handler,
            has_stable_baseline=has_baseline,
            rollback_policy=rollback_policy,
            promotion_allowed=promotion_allowed,
            blocking_reasons=tuple(blocking),
        )

    def enforce_before_promotion(
        self,
        capability_id: str,
        *,
        registered_handlers: set[str] | None = None,
    ) -> None:
        check = self.check_promotion(capability_id, registered_handlers=registered_handlers)
        if not check.promotion_allowed:
            reasons = "; ".join(check.blocking_reasons)
            raise PermissionError(
                f"BLOQUEADO por Rollback Obligatorio (Artículo III): {reasons}"
            )

    def audit_all_critical(self, registered_handlers: set[str] | None = None) -> dict[str, Any]:
        handlers = registered_handlers or set()
        critical_caps = self._list_critical_capabilities()
        checks = [self.check_promotion(cap, registered_handlers=handlers) for cap in critical_caps]
        compliant = sum(1 for c in checks if c.promotion_allowed)
        non_compliant = [c.to_dict() for c in checks if not c.promotion_allowed]
        return {
            "total_critical": len(critical_caps),
            "compliant": compliant,
            "non_compliant_count": len(non_compliant),
            "non_compliant": non_compliant,
            "status": "compliant" if not non_compliant else "non_compliant",
            "enforcement": "mandatory",
            "constitution_article": "III",
        }

    def _has_stable_baseline(self, capability_id: str) -> bool:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM stable_capability_state WHERE capability = ?",
                    (capability_id,),
                ).fetchone()
            return row is not None
        except sqlite3.OperationalError:
            return False

    def _get_rollback_policy(self, capability_id: str) -> str | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT payload_json FROM capability_registry WHERE capability_id = ? ORDER BY created_at DESC LIMIT 1",
                    (capability_id,),
                ).fetchone()
            if row:
                import json
                payload = json.loads(row["payload_json"])
                return payload.get("rollback_policy")
        except sqlite3.OperationalError:
            pass
        return None

    def _is_critical(self, capability_id: str) -> bool:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT payload_json FROM capability_registry WHERE capability_id = ? ORDER BY created_at DESC LIMIT 1",
                    (capability_id,),
                ).fetchone()
            if row:
                import json
                payload = json.loads(row["payload_json"])
                return payload.get("critical", False)
        except sqlite3.OperationalError:
            pass
        return False

    def _list_critical_capabilities(self) -> list[str]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT capability_id, payload_json FROM capability_registry"
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        import json
        critical: list[str] = []
        seen: set[str] = set()
        for row in rows:
            cap_id = row["capability_id"]
            if cap_id in seen:
                continue
            seen.add(cap_id)
            payload = json.loads(row["payload_json"])
            if payload.get("critical", False):
                critical.append(cap_id)
        return critical

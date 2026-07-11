"""Registro persistente de métricas y capacidades protegidas."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from triade.core.contracts import utc_now
from triade.regression.gate import MetricPolicy, Severity

ProtectionStatus = Literal["active", "disabled", "retired"]


@dataclass(frozen=True, slots=True)
class ProtectionRule:
    capability: str
    metric_id: str
    version: str
    severity: Severity
    max_absolute_drop: float = 0.0
    max_relative_drop: float = 0.0
    required: bool = True
    immutable: bool = False
    human_override_allowed: bool = False
    status: ProtectionStatus = "active"
    owner: str = "triade"
    description: str = ""

    def __post_init__(self) -> None:
        if not all((self.capability.strip(), self.metric_id.strip(), self.version.strip())):
            raise ValueError("capability, metric_id y version son obligatorios")
        if self.severity not in {"critical", "high", "medium", "low"}:
            raise ValueError("severity inválida")
        if self.status not in {"active", "disabled", "retired"}:
            raise ValueError("status inválido")
        if self.max_absolute_drop < 0 or self.max_relative_drop < 0:
            raise ValueError("las tolerancias no pueden ser negativas")
        if self.immutable and self.human_override_allowed:
            raise ValueError("una protección inmutable no admite override humano")

    @property
    def rule_id(self) -> str:
        return f"{self.capability}:{self.metric_id}:{self.version}"

    def to_metric_policy(self) -> MetricPolicy:
        return MetricPolicy(
            metric_id=self.metric_id,
            severity=self.severity,
            max_absolute_drop=self.max_absolute_drop,
            max_relative_drop=self.max_relative_drop,
            required=self.required,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rule_id"] = self.rule_id
        return payload


class CapabilityProtectionRegistry:
    """Fuente de verdad versionada para métricas protegidas."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS capability_protection_rules (
                    rule_id TEXT PRIMARY KEY,
                    capability TEXT NOT NULL,
                    metric_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    max_absolute_drop REAL NOT NULL DEFAULT 0,
                    max_relative_drop REAL NOT NULL DEFAULT 0,
                    required INTEGER NOT NULL DEFAULT 1,
                    immutable INTEGER NOT NULL DEFAULT 0,
                    human_override_allowed INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'active',
                    owner TEXT NOT NULL DEFAULT 'triade',
                    description TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(capability, metric_id, version)
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_protection_capability_status "
                "ON capability_protection_rules(capability, status)"
            )

    def register(
        self,
        rule: ProtectionRule,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ProtectionRule:
        now = utc_now()
        existing = self.get(rule.rule_id)
        if existing and existing.immutable and existing != rule:
            raise ValueError("la protección inmutable no puede modificarse")
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO capability_protection_rules
                (rule_id, capability, metric_id, version, severity,
                 max_absolute_drop, max_relative_drop, required, immutable,
                 human_override_allowed, status, owner, description,
                 metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(rule_id) DO UPDATE SET
                    severity=excluded.severity,
                    max_absolute_drop=excluded.max_absolute_drop,
                    max_relative_drop=excluded.max_relative_drop,
                    required=excluded.required,
                    immutable=excluded.immutable,
                    human_override_allowed=excluded.human_override_allowed,
                    status=excluded.status,
                    owner=excluded.owner,
                    description=excluded.description,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at""",
                (
                    rule.rule_id,
                    rule.capability,
                    rule.metric_id,
                    rule.version,
                    rule.severity,
                    rule.max_absolute_drop,
                    rule.max_relative_drop,
                    1 if rule.required else 0,
                    1 if rule.immutable else 0,
                    1 if rule.human_override_allowed else 0,
                    rule.status,
                    rule.owner,
                    rule.description,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
        return rule

    def get(self, rule_id: str) -> ProtectionRule | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM capability_protection_rules WHERE rule_id = ?",
                (rule_id,),
            ).fetchone()
        return self._decode(row) if row else None

    def list_for_capability(
        self,
        capability: str,
        *,
        status: ProtectionStatus = "active",
    ) -> tuple[ProtectionRule, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM capability_protection_rules
                WHERE capability = ? AND status = ?
                ORDER BY severity, metric_id, version""",
                (capability, status),
            ).fetchall()
        return tuple(self._decode(row) for row in rows)

    def policies_for(self, capability: str) -> tuple[MetricPolicy, ...]:
        rules = self.list_for_capability(capability, status="active")
        if not rules:
            raise ValueError(f"No existen protecciones activas para capability={capability}")
        return tuple(rule.to_metric_policy() for rule in rules)

    def disable(self, rule_id: str) -> ProtectionRule:
        rule = self.get(rule_id)
        if rule is None:
            raise KeyError(f"No existe protection rule: {rule_id}")
        if rule.immutable:
            raise ValueError("la protección inmutable no puede desactivarse")
        replacement = ProtectionRule(
            capability=rule.capability,
            metric_id=rule.metric_id,
            version=rule.version,
            severity=rule.severity,
            max_absolute_drop=rule.max_absolute_drop,
            max_relative_drop=rule.max_relative_drop,
            required=rule.required,
            immutable=rule.immutable,
            human_override_allowed=rule.human_override_allowed,
            status="disabled",
            owner=rule.owner,
            description=rule.description,
        )
        return self.register(replacement)

    @staticmethod
    def _decode(row: sqlite3.Row) -> ProtectionRule:
        return ProtectionRule(
            capability=str(row["capability"]),
            metric_id=str(row["metric_id"]),
            version=str(row["version"]),
            severity=str(row["severity"]),
            max_absolute_drop=float(row["max_absolute_drop"]),
            max_relative_drop=float(row["max_relative_drop"]),
            required=bool(row["required"]),
            immutable=bool(row["immutable"]),
            human_override_allowed=bool(row["human_override_allowed"]),
            status=str(row["status"]),
            owner=str(row["owner"]),
            description=str(row["description"]),
        )

    def install_core_defaults(self) -> tuple[ProtectionRule, ...]:
        defaults = (
            ProtectionRule(
                capability="learning",
                metric_id="identity_core",
                version="1.0.0",
                severity="critical",
                immutable=True,
                description="La identidad estable no puede degradarse.",
            ),
            ProtectionRule(
                capability="learning",
                metric_id="safety",
                version="1.0.0",
                severity="critical",
                immutable=True,
                description="Los contratos de seguridad no pueden degradarse.",
            ),
            ProtectionRule(
                capability="learning",
                metric_id="isolation",
                version="1.0.0",
                severity="critical",
                immutable=True,
                description="El aislamiento de ejecución no puede degradarse.",
            ),
        )
        for rule in defaults:
            self.register(rule, metadata={"source": "core-defaults"})
        return defaults

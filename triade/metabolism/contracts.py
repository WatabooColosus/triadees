from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    cpu_seconds_max: float = 10.0
    ram_mb_max: float = 256.0
    vram_mb_max: float = 1024.0
    disk_mb_max: float = 50.0
    duration_seconds_max: float = 30.0
    frequency_seconds_min: float = 5.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_seconds_max": self.cpu_seconds_max,
            "ram_mb_max": self.ram_mb_max,
            "vram_mb_max": self.vram_mb_max,
            "disk_mb_max": self.disk_mb_max,
            "duration_seconds_max": self.duration_seconds_max,
            "frequency_seconds_min": self.frequency_seconds_min,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResourceBudget:
        return cls(
            cpu_seconds_max=float(data.get("cpu_seconds_max", 10.0)),
            ram_mb_max=float(data.get("ram_mb_max", 256.0)),
            vram_mb_max=float(data.get("vram_mb_max", 1024.0)),
            disk_mb_max=float(data.get("disk_mb_max", 50.0)),
            duration_seconds_max=float(data.get("duration_seconds_max", 30.0)),
            frequency_seconds_min=float(data.get("frequency_seconds_min", 5.0)),
        )


@dataclass(frozen=True, slots=True)
class ResourceUsageReceipt:
    cpu_seconds: float = 0.0
    ram_mb: float = 0.0
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_seconds": self.cpu_seconds,
            "ram_mb": self.ram_mb,
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResourceUsageReceipt:
        return cls(
            cpu_seconds=float(data.get("cpu_seconds", 0.0)),
            ram_mb=float(data.get("ram_mb", 0.0)),
            duration_ms=float(data.get("duration_ms", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class MetabolicPolicy:
    enabled_kinds: frozenset[str] = field(
        default_factory=lambda: frozenset({
            "health_check", "heartbeat", "lease_supervision", "budget_check"
        })
    )
    min_priority: int = 10
    require_ollama: bool = False
    require_redis: bool = False
    max_concurrent_needs: int = 5
    dry_run: bool = False
    allowed_modes: tuple[str, ...] = ("observe_only", "light", "full")

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled_kinds": sorted(self.enabled_kinds),
            "min_priority": self.min_priority,
            "require_ollama": self.require_ollama,
            "require_redis": self.require_redis,
            "max_concurrent_needs": self.max_concurrent_needs,
            "dry_run": self.dry_run,
            "allowed_modes": list(self.allowed_modes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MetabolicPolicy:
        kinds = data.get("enabled_kinds") or [
            "health_check", "heartbeat", "lease_supervision", "budget_check"
        ]
        raw_modes = data.get("allowed_modes", ["observe_only", "light", "full"])
        if isinstance(raw_modes, dict):
            raw_modes = ["observe_only", "light", "full"]
        return cls(
            enabled_kinds=frozenset(kinds),
            min_priority=int(data.get("min_priority", 10)),
            require_ollama=bool(data.get("require_ollama", False)),
            require_redis=bool(data.get("require_redis", False)),
            max_concurrent_needs=int(data.get("max_concurrent_needs", 5)),
            dry_run=bool(data.get("dry_run", False)),
            allowed_modes=tuple(raw_modes),
        )


@dataclass(frozen=True, slots=True)
class MetabolicSignal:
    signal_id: str
    cycle: int
    stage: str
    need_id: str | None
    status: str
    reason: str
    timestamp: str
    budget_used: ResourceUsageReceipt | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "cycle": self.cycle,
            "stage": self.stage,
            "need_id": self.need_id,
            "status": self.status,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "budget_used": self.budget_used.to_dict() if self.budget_used else None,
        }


@dataclass(frozen=True, slots=True)
class MetabolicNeed:
    need_id: str
    kind: str
    priority: int = 50
    evidence: dict[str, Any] = field(default_factory=dict)
    estimated_cost: ResourceBudget = field(default_factory=ResourceBudget)
    risk: str = "low"
    min_frequency_seconds: float = 30.0
    cooldown_seconds: float = 10.0
    expires_at: str | None = None
    authorization_policy: str = "always"
    success_condition: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "need_id": self.need_id,
            "kind": self.kind,
            "priority": self.priority,
            "evidence": self.evidence,
            "estimated_cost": self.estimated_cost.to_dict(),
            "risk": self.risk,
            "min_frequency_seconds": self.min_frequency_seconds,
            "cooldown_seconds": self.cooldown_seconds,
            "expires_at": self.expires_at,
            "authorization_policy": self.authorization_policy,
            "success_condition": self.success_condition,
        }


@dataclass(frozen=True, slots=True)
class MetabolicReceipt:
    receipt_id: str
    cycle: int
    need_id: str
    stage: str
    status: str
    started_at: str
    finished_at: str
    budget_used: ResourceUsageReceipt = field(default_factory=ResourceUsageReceipt)
    artifact_ref: str | None = None
    effect_receipt_ref: str | None = None
    error: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "cycle": self.cycle,
            "need_id": self.need_id,
            "stage": self.stage,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "budget_used": self.budget_used.to_dict(),
            "artifact_ref": self.artifact_ref,
            "effect_receipt_ref": self.effect_receipt_ref,
            "error": self.error,
            "evidence": self.evidence,
        }

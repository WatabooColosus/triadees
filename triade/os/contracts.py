"""Contratos de datos para TriadeOS — Sistema Operativo Cognitivo."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


# ── Knowledge Graph ──────────────────────────────────────────

KGNodeType = Literal["fact", "concept", "entity", "claim", "hypothesis"]
KGEvidenceLevel = Literal["candidate", "contested", "corroborated", "established", "canonical"]
KGRelationType = Literal["supports", "contradicts", "refines", "depends_on", "originates_from", "related_to"]
KGResolutionStatus = Literal["unresolved", "investigating", "resolved", "accepted"]


@dataclass(slots=True)
class KGNode:
    id: int | None = None
    node_type: KGNodeType = "fact"
    content: str = ""
    domain: str | None = None
    evidence_level: KGEvidenceLevel = "candidate"
    confidence: float = 0.0
    source_ref: str | None = None
    neuron_id: int | None = None
    created_at: str = ""
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "node_type": self.node_type,
            "content": self.content,
            "domain": self.domain,
            "evidence_level": self.evidence_level,
            "confidence": self.confidence,
            "source_ref": self.source_ref,
            "neuron_id": self.neuron_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class KGEdge:
    id: int | None = None
    source_id: int = 0
    target_id: int = 0
    relation_type: KGRelationType = "related_to"
    weight: float = 1.0
    evidence_refs: list[str] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.relation_type,
            "weight": self.weight,
            "evidence_refs": self.evidence_refs,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class KGContradiction:
    id: int | None = None
    node_a_id: int = 0
    node_b_id: int = 0
    description: str | None = None
    resolution_status: KGResolutionStatus = "unresolved"
    resolution: str | None = None
    resolved_at: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "node_a_id": self.node_a_id,
            "node_b_id": self.node_b_id,
            "description": self.description,
            "resolution_status": self.resolution_status,
            "resolution": self.resolution,
            "resolved_at": self.resolved_at,
            "created_at": self.created_at,
        }


# ── Event Engine ─────────────────────────────────────────────

@dataclass(slots=True)
class EventRule:
    event_type_pattern: str
    source_pattern: str | None = None
    severity_min: str = "ok"
    action: str = ""
    priority: int = 50
    cooldown_seconds: int = 300
    dedup_window_seconds: int = 60

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type_pattern": self.event_type_pattern,
            "source_pattern": self.source_pattern,
            "severity_min": self.severity_min,
            "action": self.action,
            "priority": self.priority,
            "cooldown_seconds": self.cooldown_seconds,
            "dedup_window_seconds": self.dedup_window_seconds,
        }


SEVERITY_ORDER = {"ok": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}


# ── Neuron Scheduler ─────────────────────────────────────────

@dataclass(slots=True)
class NeuronPriority:
    neuron_id: int = 0
    neuron_name: str = ""
    priority_score: float = 0.0
    evidence_gap: float = 0.0
    staleness: float = 0.0
    impact: float = 0.0
    reputation: float = 0.5
    resource_freshness: float = 1.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "neuron_id": self.neuron_id,
            "neuron_name": self.neuron_name,
            "priority_score": round(self.priority_score, 4),
            "evidence_gap": round(self.evidence_gap, 4),
            "staleness": round(self.staleness, 4),
            "impact": round(self.impact, 4),
            "reputation": round(self.reputation, 4),
            "resource_freshness": round(self.resource_freshness, 4),
            "reason": self.reason,
        }


# ── TriadeOS Config ──────────────────────────────────────────

@dataclass(slots=True)
class TriadeOSConfig:
    enabled: bool = True
    knowledge_graph_enabled: bool = True
    event_engine_enabled: bool = True
    scheduler_enabled: bool = True
    max_consolidations_per_cycle: int = 3
    min_confidence_to_consolidate: float = 0.70
    scan_interval_seconds: int = 60
    max_wakeups_per_cycle: int = 5

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "knowledge_graph_enabled": self.knowledge_graph_enabled,
            "event_engine_enabled": self.event_engine_enabled,
            "scheduler_enabled": self.scheduler_enabled,
            "max_consolidations_per_cycle": self.max_consolidations_per_cycle,
            "min_confidence_to_consolidate": self.min_confidence_to_consolidate,
            "scan_interval_seconds": self.scan_interval_seconds,
            "max_wakeups_per_cycle": self.max_wakeups_per_cycle,
        }

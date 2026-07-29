"""Orquestación multi-modelo con decisiones explicables y adopción medida."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

SCHEMA = Path(__file__).resolve().parent.parent / "memory/schemas.sql"
MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "memory/migrations/027_measured_model_orchestration.sql"
)
Role = Literal[
    "planner", "coder", "critic", "evaluator", "embedding", "vision", "summarizer"
]
ROLES: tuple[Role, ...] = (
    "planner",
    "coder",
    "critic",
    "evaluator",
    "embedding",
    "vision",
    "summarizer",
)


@dataclass(frozen=True, slots=True)
class ModelCapability:
    model: str
    roles: frozenset[Role]
    quality: dict[Role, float]
    latency_ms: float
    vram_gb: float
    ram_gb: float
    available: bool
    private: bool
    context_tokens: int


@dataclass(frozen=True, slots=True)
class RouteRequirements:
    max_latency_ms: float
    max_vram_gb: float
    max_ram_gb: float
    require_private: bool = True
    context_tokens: int = 0


@dataclass(frozen=True, slots=True)
class MeasuredRoute:
    route_id: str
    role: Role
    selected_model: str | None
    reason: str
    fallback_used: bool
    unload_previous_gpu_model: bool


class MeasuredModelOrchestrator:
    def __init__(
        self, db_path: str | Path, capabilities: list[ModelCapability]
    ) -> None:
        self.db_path = Path(db_path)
        self.capabilities = capabilities
        self.active_gpu_model: str | None = None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA.read_text(encoding="utf-8"))
            conn.executescript(MIGRATION.read_text(encoding="utf-8"))

    def route(
        self, role: Role, requirements: RouteRequirements, fallback: str | None = None
    ) -> MeasuredRoute:
        eligible = [
            item
            for item in self.capabilities
            if item.available
            and role in item.roles
            and item.latency_ms <= requirements.max_latency_ms
            and item.vram_gb <= requirements.max_vram_gb
            and item.ram_gb <= requirements.max_ram_gb
            and (not requirements.require_private or item.private)
            and item.context_tokens >= requirements.context_tokens
        ]
        eligible.sort(
            key=lambda item: (
                -item.quality.get(role, 0.0),
                item.latency_ms,
                item.vram_gb,
            )
        )
        selected = eligible[0].model if eligible else fallback
        fallback_used = not eligible
        reason = (
            "highest_measured_role_quality_within_resource_policy"
            if eligible
            else "no_eligible_model_explicit_fallback"
            if fallback
            else "no_eligible_model"
        )
        unload = bool(
            selected
            and self.active_gpu_model
            and selected != self.active_gpu_model
            and next(
                item.vram_gb for item in self.capabilities if item.model == selected
            )
            > 0
        )
        if selected and any(
            item.model == selected and item.vram_gb > 0 for item in self.capabilities
        ):
            self.active_gpu_model = selected
        route = MeasuredRoute(
            f"mr-{uuid.uuid4().hex}", role, selected, reason, fallback_used, unload
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO measured_model_routes VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    route.route_id,
                    role,
                    selected,
                    reason,
                    int(fallback_used),
                    json.dumps(asdict(requirements), sort_keys=True),
                    datetime.now(UTC).isoformat(),
                ),
            )
        return route

    def evaluate_adoption(
        self,
        *,
        baseline_model: str,
        routes: list[MeasuredRoute],
        baseline_metrics: dict[str, float] | None,
        candidate_metrics: dict[str, float] | None,
    ) -> dict[str, Any]:
        rollback_ref = f"model-routing:restore:{baseline_model}"
        complete = baseline_metrics is not None and candidate_metrics is not None
        if baseline_metrics is not None and candidate_metrics is not None:
            quality_gain = candidate_metrics["quality"] - baseline_metrics["quality"]
            resource_gain = (
                baseline_metrics["resource_cost"] - candidate_metrics["resource_cost"]
            )
        else:
            quality_gain = 0.0
            resource_gain = 0.0
        adopted = complete and quality_gain >= 0 and resource_gain > 0
        reason = (
            "measured_improvement" if adopted else "benchmark_missing_or_no_improvement"
        )
        decision = {
            "decision_id": f"md-{uuid.uuid4().hex}",
            "adopted": adopted,
            "rollback_ref": rollback_ref,
            "reason": reason,
            "quality_gain": quality_gain,
            "resource_gain": resource_gain,
        }
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO model_adoption_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    decision["decision_id"],
                    baseline_model,
                    json.dumps([asdict(route) for route in routes]),
                    json.dumps(baseline_metrics) if baseline_metrics else None,
                    json.dumps(candidate_metrics) if candidate_metrics else None,
                    int(adopted),
                    rollback_ref,
                    reason,
                    datetime.now(UTC).isoformat(),
                ),
            )
        return decision

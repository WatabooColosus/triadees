"""Contrato común, append-only, para enlazar un ciclo cognitivo completo.

El contrato no inventa evidencia: sólo normaliza las referencias que cada
órgano ya produce. Un consumidor puede construir el registro al final de un
ciclo y comprobar qué etapas realmente dejaron estado observable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


STAGES = ("hardware", "metabolism", "hypothalamus", "central", "qualia", "crystal", "learning")


@dataclass(slots=True)
class CognitiveCycleTrace:
    run_id: str
    cycle_id: str | int | None = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    mode_requested: str | None = None
    mode_effective: str | None = None
    stages: dict[str, dict[str, Any]] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def record_stage(self, stage: str, *, status: str, evidence_ref: str | None = None, **data: Any) -> None:
        if stage not in STAGES:
            raise ValueError(f"unknown cognitive stage: {stage}")
        entry = {"status": status, **data}
        if evidence_ref:
            entry["evidence_ref"] = evidence_ref
            if evidence_ref not in self.evidence_refs:
                self.evidence_refs.append(evidence_ref)
        self.stages[stage] = entry

    def finish(self, *, status: str = "completed", error: str | None = None) -> None:
        self.completed_at = datetime.now(timezone.utc).isoformat()
        if error:
            self.errors.append(error)
        self.stages.setdefault("learning", {"status": status})

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["stage_order"] = list(STAGES)
        payload["observed_stage_count"] = len(self.stages)
        payload["complete"] = all(stage in self.stages for stage in STAGES)
        return payload

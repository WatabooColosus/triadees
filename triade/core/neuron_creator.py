"""N Creadora · órgano interno de diseño de neuronas.

La N Creadora diseña especificaciones, contratos y límites.
No activa neuronas estables por sí sola.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class NeuronSpec:
    name: str
    mission: str
    domain: str
    rules: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    inputs_allowed: list[str] = field(default_factory=list)
    outputs_allowed: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)
    success_metrics: list[str] = field(default_factory=list)
    evidence_required: list[str] = field(default_factory=list)
    status: str = "candidate_detected"
    created_by: str = "neuron_creator"
    policy: str = "creator_only_no_activation_without_trainer_and_human_review"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NeuronCreator:
    """Diseña especificaciones de neuronas candidatas."""

    def create(
        self,
        name: str,
        mission: str,
        domain: str,
        rules: list[str] | None = None,
        triggers: list[str] | None = None,
        inputs_allowed: list[str] | None = None,
        outputs_allowed: list[str] | None = None,
        forbidden_actions: list[str] | None = None,
        success_metrics: list[str] | None = None,
        evidence_required: list[str] | None = None,
    ) -> NeuronSpec:
        clean_name = self._clean(name) or "neurona_candidata"
        clean_mission = self._clean(mission) or "Misión pendiente de definición."
        clean_domain = self._clean(domain) or "general"

        base_rules = [
            "Operar dentro del ciclo auditable de Tríade.",
            "No modificar memoria estable sin validación humana.",
            "Producir salidas verificables.",
            "No ejecutar acciones externas sin autorización explícita.",
            "No aprobarse a sí misma ni elevar su propio estado.",
        ]

        base_forbidden = [
            "modify_repo_directly",
            "write_stable_memory",
            "self_approve",
            "bypass_safety",
            "execute_external_action_without_approval",
        ]

        final_rules = base_rules + [self._clean(rule) for rule in (rules or []) if self._clean(rule)]
        final_forbidden = base_forbidden + [self._clean(x) for x in (forbidden_actions or []) if self._clean(x)]

        return NeuronSpec(
            name=clean_name,
            mission=clean_mission,
            domain=clean_domain,
            rules=final_rules,
            triggers=[self._clean(x) for x in (triggers or []) if self._clean(x)],
            inputs_allowed=[self._clean(x) for x in (inputs_allowed or []) if self._clean(x)],
            outputs_allowed=[self._clean(x) for x in (outputs_allowed or []) if self._clean(x)],
            forbidden_actions=final_forbidden,
            success_metrics=[self._clean(x) for x in (success_metrics or []) if self._clean(x)],
            evidence_required=[self._clean(x) for x in (evidence_required or []) if self._clean(x)],
            status="candidate_detected",
        )

    @staticmethod
    def _clean(value: str) -> str:
        return " ".join(str(value).strip().split())

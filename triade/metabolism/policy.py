from __future__ import annotations

from typing import Any

from triade.metabolism.contracts import MetabolicNeed, MetabolicPolicy


class PolicyEngine:
    def __init__(self, policy: MetabolicPolicy | None = None) -> None:
        self.policy = policy or MetabolicPolicy()

    def authorize(self, need: MetabolicNeed, mode: str) -> tuple[bool, str]:
        if mode not in self.policy.allowed_modes:
            return False, f"mode_{mode}_not_allowed"
        if need.kind not in self.policy.enabled_kinds:
            return False, f"kind_{need.kind}_not_enabled"
        if need.priority < self.policy.min_priority:
            return False, f"priority_{need.priority}_below_min_{self.policy.min_priority}"
        if need.authorization_policy == "never":
            return False, "authorization_policy_is_never"
        return True, ""

    def can_execute(self, need: MetabolicNeed, mode: str) -> tuple[bool, str]:
        return self.authorize(need, mode)

    def reload(self, config: dict[str, Any]) -> None:
        policy_dict = config.get("policy", {})
        self.policy = MetabolicPolicy.from_dict(policy_dict)
        needs_config = config.get("needs", {})
        enabled_kinds = set(self.policy.enabled_kinds)
        for kind, cfg in needs_config.items():
            if isinstance(cfg, dict) and not cfg.get("enabled", True):
                enabled_kinds.discard(kind)
        self.policy = MetabolicPolicy(
            enabled_kinds=frozenset(enabled_kinds),
            min_priority=self.policy.min_priority,
            require_ollama=self.policy.require_ollama,
            require_redis=self.policy.require_redis,
            max_concurrent_needs=self.policy.max_concurrent_needs,
            dry_run=self.policy.dry_run,
            allowed_modes=self.policy.allowed_modes,
        )

    def snapshot(self) -> dict[str, Any]:
        return self.policy.to_dict()

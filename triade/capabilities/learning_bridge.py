from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.learning.evidence_bridge import LearningEvidenceBridge

from .bootstrap import bootstrap_core_capabilities
from .policy import CapabilityPolicyGuard


class GovernedLearningEvidenceBridge(LearningEvidenceBridge):
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        bootstrap_core_capabilities(db_path)
        super().__init__(db_path=db_path)
        self.capability_guard = CapabilityPolicyGuard(db_path)

    def require_improvement(self, candidate_id: str) -> dict[str, Any]:
        self.capability_guard.require("learning-promotion", "promote")
        evidence = super().require_improvement(candidate_id)
        evidence["capability_authorization"] = {
            "capability_id": "learning-promotion",
            "action": "promote",
            "allowed": True,
        }
        return evidence

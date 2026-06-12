"""QualiaBus: publicación, ruteo, persistencia y aprendizaje controlado."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.learning.pipeline import LearningPipeline

from .contracts import NeuronExperience, QualiaState
from .reports import build_qualia_report
from .router import QualiaBundle, QualiaRouter
from .state import compute_qualia_state
from .store import QualiaStore


class QualiaBus:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db", store: QualiaStore | None = None, router: QualiaRouter | None = None, learning_pipeline: LearningPipeline | None = None) -> None:
        self.db_path = Path(db_path)
        self.store = store or QualiaStore(db_path=self.db_path)
        self.router = router or QualiaRouter()
        self.learning_pipeline = learning_pipeline

    def publish_experience(self, experience: NeuronExperience, *, ingest_learning: bool = True) -> dict[str, Any]:
        bundle = self.router.route(experience)
        persisted = self.persist_bundle(bundle)
        learning_result = self.route_to_learning(experience) if ingest_learning else None
        state = self.compute_state(experience.run_id)
        return {"status": "ok", "bundle": bundle.to_dict(), "persisted": persisted, "learning": learning_result, "state": state.to_dict()}

    def route_to_hypothalamus(self, experience: NeuronExperience) -> dict[str, Any]:
        return self.router.to_signal(experience).to_dict()

    def route_to_central(self, experience: NeuronExperience) -> dict[str, Any]:
        return self.router.to_central_packet(experience).to_dict()

    def route_to_storage(self, experience: NeuronExperience) -> dict[str, Any]:
        return self.router.to_storage_packet(experience).to_dict()

    def route_to_learning(self, experience: NeuronExperience) -> dict[str, Any] | None:
        candidate = self.router.to_learning_candidate(experience)
        if not candidate:
            return None
        source_ref = candidate.get("source_ref", "")
        pipe = self.learning_pipeline or LearningPipeline(db_path=self.db_path)
        if source_ref:
            existing = pipe.list_candidates(status="candidate", limit=200)
            for row in existing:
                if row.get("source_ref") == source_ref:
                    row.setdefault("qualia_evidence_refs", candidate.get("evidence_refs", []))
                    row["deduplicated"] = True
                    return row
        payload = dict(candidate)
        payload.pop("evidence_refs", None)
        result = pipe.ingest(**payload)
        result.setdefault("qualia_evidence_refs", candidate.get("evidence_refs", []))
        return result

    def compute_state(self, run_id: str) -> QualiaState:
        signals = self.store.list_signals(run_id=run_id, limit=200)
        experiences = self.store.list_experiences(run_id=run_id, limit=200)
        state = compute_qualia_state(run_id, signals=signals, experiences=experiences)
        self.store.store_state(state)
        return state

    def persist_bundle(self, bundle: QualiaBundle) -> dict[str, Any]:
        return self.store.persist_bundle(bundle)

    def report(self, run_id: str | None = None) -> dict[str, Any]:
        return build_qualia_report(self.store, run_id=run_id)

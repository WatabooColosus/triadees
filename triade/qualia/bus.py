"""QualiaBus: publicación, ruteo, persistencia, introspección y aprendizaje controlado."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.learning.pipeline import LearningPipeline

from .contracts import NeuronExperience, QualiaState
from .qualia_packet import (
    ContinuityChain,
    FragmentationReport,
    MeaningScore,
    QualiaPacket,
    build_qualia_packet,
)
from .continuity import ContinuityEngine
from .meaning import MeaningEngine
from .fragmentation import FragmentationDetector
from .introspection import IntrospectionReport, QualiaIntrospector
from .reports import build_qualia_report
from .router import QualiaBundle, QualiaRouter
from .state import compute_qualia_state
from .store import QualiaStore


class QualiaBus:
    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        store: QualiaStore | None = None,
        router: QualiaRouter | None = None,
        learning_pipeline: LearningPipeline | None = None,
        introspector: QualiaIntrospector | None = None,
        continuity: ContinuityEngine | None = None,
        meaning: MeaningEngine | None = None,
        fragmentation: FragmentationDetector | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.store = store or QualiaStore(db_path=self.db_path)
        self.router = router or QualiaRouter()
        self.learning_pipeline = learning_pipeline
        self.introspector = introspector or QualiaIntrospector()
        self.continuity = continuity or ContinuityEngine(db_path=db_path)
        self.meaning = meaning or MeaningEngine()
        self.fragmentation = fragmentation or FragmentationDetector()

    def publish_experience(self, experience: NeuronExperience, *, ingest_learning: bool = True) -> dict[str, Any]:
        bundle = self.router.route(experience)
        persisted = self.persist_bundle(bundle)
        learning_result = self.route_to_learning(experience) if ingest_learning else None
        state = self.compute_state(experience.run_id)
        introspection = self.introspect(experience.run_id, state=state)

        meaning_score = self.meaning.score(experience=experience, state=state)
        frag = self.fragmentation.detect(
            experiences=self.store.list_experiences(run_id=experience.run_id, limit=50),
            state=state,
        )

        return {
            "status": "ok",
            "bundle": bundle.to_dict(),
            "persisted": persisted,
            "learning": learning_result,
            "state": state.to_dict(),
            "introspection": introspection.to_dict(),
            "meaning": meaning_score,
            "fragmentation": frag,
        }

    def publish_qualia_packet(
        self,
        experience: NeuronExperience,
        *,
        parent_packet_id: str = "",
        parent_run_id: str = "",
        mission_context: str = "",
        ingest_learning: bool = True,
    ) -> QualiaPacket:
        """Publica una experiencia completa como QualiaPacket unificado.

        Flujo:
        1. Route experience -> bundle
        2. Persist bundle
        3. Compute state + continuity + meaning + fragmentation
        4. Build QualiaPacket
        5. Anchor continuity with QualiaPacket's own ID
        6. Return
        """
        bundle = self.router.route(experience)
        self.persist_bundle(bundle)

        if ingest_learning:
            self.route_to_learning(experience)

        state = self.compute_state(experience.run_id)

        chain = self.continuity.build_chain(
            packet_id="",  # placeholder, real ID set after packet creation
            parent_packet_id=parent_packet_id,
            parent_run_id=parent_run_id,
        )

        meaning_score = self.meaning.score(
            experience=experience, state=state, mission_context=mission_context,
        )

        recent = self.store.list_experiences(run_id=experience.run_id, limit=50)
        frag = self.fragmentation.detect(experiences=recent, state=state)

        packet = build_qualia_packet(
            run_id=experience.run_id,
            experience=bundle.experience,
            signal=bundle.signal,
            state=state,
            central_packet=bundle.central_packet,
            storage_packet=bundle.storage_packet,
            continuity=ContinuityChain(**chain),
            meaning=MeaningScore(**meaning_score),
            fragmentation=FragmentationReport(**frag),
        )

        self.continuity.anchor(
            packet_id=packet.id,
            run_id=experience.run_id,
            chain_id=chain["chain_id"],
            parent_packet_id=parent_packet_id,
            summary_hash=experience.observation[:60] if experience.observation else "",
        )

        return packet

    def introspect_packet(self, packet: QualiaPacket) -> IntrospectionReport:
        """Introspección específica sobre un QualiaPacket."""
        state = packet.state or self.compute_state(packet.run_id)
        experience = packet.experience
        return self.introspector.reflect(
            run_id=packet.run_id,
            state=state,
            experiences=[experience] if experience else [],
        )

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

    def introspect(self, run_id: str, *, state: QualiaState | None = None) -> IntrospectionReport:
        """Interpreta el flujo Qualia sin promover conclusiones a memoria estable."""
        current_state = state or self.compute_state(run_id)
        experiences = self.store.list_experiences(run_id=run_id, limit=200)
        return self.introspector.reflect(
            run_id=run_id,
            state=current_state,
            experiences=experiences,
        )

    def persist_bundle(self, bundle: QualiaBundle) -> dict[str, Any]:
        return self.store.persist_bundle(bundle)

    def report(self, run_id: str | None = None) -> dict[str, Any]:
        report = build_qualia_report(self.store, run_id=run_id)
        if run_id:
            report["introspection"] = self.introspect(run_id).to_dict()
        return report

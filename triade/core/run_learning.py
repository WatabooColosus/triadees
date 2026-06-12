"""Servicios de aprendizaje y continuidad derivados de un run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.learning.pipeline import LearningPipeline
from triade.memory.semantic_continuity import SemanticContinuity

from .contracts import InputPacket


class RunLearningService:
    """Encapsula persistencia candidate-only posterior al run."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def semantic_continuity(
        self,
        *,
        input_packet: InputPacket,
        output: Any,
        intent: str,
        crystal: Any,
        model_selection: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return SemanticContinuity(db_path=self.db_path, auto_ollama_embed=False).ingest_run(
                run_id=input_packet.run_id,
                user_input=input_packet.user_input,
                response=output.response,
                source=input_packet.source,
                intent=intent,
                q_crystal=crystal.q_crystal,
                stability=crystal.stability,
                model_summary={
                    "central": {
                        "provider": output.model_provider,
                        "name": output.model_name,
                        "ok": output.model_ok,
                    },
                    "selection": model_selection,
                },
            )
        except Exception as exc:
            return {
                "status": "error",
                "mode": "semantic-continuity",
                "error": str(exc),
                "policy": {"auto_consolidation": False, "identity_core_modified": False},
            }

    def post_run_learning_candidate(
        self,
        *,
        input_packet: InputPacket,
        output: Any,
        report: Any,
        intent: str,
    ) -> dict[str, Any]:
        context = input_packet.context or {}
        domain = str(context.get("domain", "")).strip() or str(intent or "general")
        content = "\n".join(
            [
                f"run_id: {input_packet.run_id}",
                f"source: {input_packet.source}",
                f"intent: {intent}",
                f"input: {input_packet.user_input}",
                f"response: {output.response}",
                f"verification_status: {report.status}",
            ]
        )
        candidate = LearningPipeline(db_path=self.db_path).ingest(
            content=content,
            source_type="conversation",
            source_ref=f"run:{input_packet.run_id}",
            title=f"Post-run learning {input_packet.run_id}",
            domain=domain,
            risk_level="low",
        )
        return {
            "enabled": True,
            "mode": "candidate_only",
            "candidate_id": candidate.get("candidate_id"),
            "status": candidate.get("status"),
            "source_ref": candidate.get("source_ref"),
            "policy": "No se evalua, verifica ni consolida sin pasos explicitos posteriores.",
        }

"""Adaptador de rollback real para la capacidad de aprendizaje."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from triade.learning.pipeline import LearningPipeline
from triade.memory.semantic_governance import SemanticMemoryGovernance

from .rollback import RollbackExecutor


class LearningRollbackAdapter:
    """Retira un candidato degradado y confirma el último aprendizaje estable."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.pipeline = LearningPipeline(db_path=self.db_path)
        self.governance = SemanticMemoryGovernance(db_path=self.db_path)

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("capability") != "learning":
            return {"applied": False, "error": "capability no soportada por LearningRollbackAdapter"}

        failed_candidate_id = str(request.get("candidate_id") or "").strip()
        target = dict(request.get("target") or {})
        stable_candidate_id = str(target.get("subject_id") or "").strip()
        if not failed_candidate_id or not stable_candidate_id:
            return {"applied": False, "error": "candidate_id y target.subject_id son obligatorios"}
        if failed_candidate_id == stable_candidate_id:
            return {"applied": False, "error": "el candidato degradado no puede ser el target estable"}

        failed = self.pipeline.get_candidate(failed_candidate_id)
        stable = self.pipeline.get_candidate(stable_candidate_id)
        if failed is None:
            return {"applied": False, "error": f"no existe candidato degradado: {failed_candidate_id}"}
        if stable is None:
            return {"applied": False, "error": f"no existe candidato estable: {stable_candidate_id}"}
        if stable.get("status") != "consolidated":
            return {"applied": False, "error": "el target de aprendizaje no está consolidated"}

        stable_document = self._document_for_candidate(stable_candidate_id)
        if stable_document is None or stable_document.get("status") != "stable":
            return {"applied": False, "error": "el target no tiene memoria semántica stable"}

        failed_document = self._document_for_candidate(failed_candidate_id)
        before_state = {
            "subject_id": failed_candidate_id,
            "candidate_status": failed.get("status"),
            "semantic_document_id": failed_document.get("document_id") if failed_document else None,
            "semantic_status": failed_document.get("status") if failed_document else None,
        }

        if failed_document and failed_document.get("status") != "rejected":
            self.governance.transition_document(
                str(failed_document["document_id"]),
                "rejected",
                reason=f"Rollback por Regression Gate: {request.get('report_id')}",
                approved_by=str(request.get("requested_by") or "regression-gate"),
                evidence={
                    "rollback_id": request.get("rollback_id"),
                    "candidate_id": failed_candidate_id,
                    "target_candidate_id": stable_candidate_id,
                    "report_id": request.get("report_id"),
                },
            )

        if failed.get("status") != "archived":
            self.pipeline.archive(failed_candidate_id)

        after_state = {
            "subject_id": stable_candidate_id,
            "candidate_status": stable.get("status"),
            "semantic_document_id": stable_document.get("document_id"),
            "semantic_status": stable_document.get("status"),
            "retired_candidate_id": failed_candidate_id,
            "retired_candidate_status": (self.pipeline.get_candidate(failed_candidate_id) or {}).get("status"),
            "retired_semantic_status": (
                (self._document_for_candidate(failed_candidate_id) or {}).get("status")
                if failed_document
                else None
            ),
        }
        return {"applied": True, "before_state": before_state, "after_state": after_state}

    def _document_for_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM semantic_documents WHERE source_type = 'learning_pipeline' ORDER BY id DESC"
            ).fetchall()
        for row in rows:
            item = dict(row)
            try:
                metadata = json.loads(item.get("metadata") or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            if metadata.get("learning_candidate_id") == candidate_id:
                item["metadata"] = metadata
                return item
        return None


def register_learning_rollback(
    executor: RollbackExecutor,
    db_path: str | Path = "triade/memory/triade.db",
) -> LearningRollbackAdapter:
    """Registra el único handler permitido para rollback de aprendizaje."""

    adapter = LearningRollbackAdapter(db_path=db_path)
    executor.register_handler("learning", adapter)
    return adapter

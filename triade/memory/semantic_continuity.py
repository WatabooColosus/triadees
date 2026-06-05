"""Continuidad semántica real para Tríade.

Cada run puede dejar un documento semántico candidato y un vector verificable.
No consolida a stable ni toca identity_core.
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from triade.memory.semantic_embedding_engine import SemanticEmbeddingEngine
from triade.memory.semantic_store import SemanticMemoryStore


LOCAL_HASH_MODEL = "triade-local-hash:64"


@dataclass(slots=True)
class SemanticContinuity:
    db_path: str | Path = "triade/memory/triade.db"
    auto_ollama_embed: bool = True
    store: SemanticMemoryStore = field(init=False)

    def __post_init__(self) -> None:
        self.store = SemanticMemoryStore(db_path=self.db_path)

    def ingest_run(
        self,
        run_id: str,
        user_input: str,
        response: str,
        source: str,
        intent: str,
        q_crystal: float | None = None,
        stability: float | None = None,
        model_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        content = self._run_content(
            run_id=run_id,
            user_input=user_input,
            response=response,
            source=source,
            intent=intent,
            q_crystal=q_crystal,
            stability=stability,
        )
        document = self.store.upsert_document(
            content=content,
            domain=f"run:{intent or 'conversation'}",
            source_type="conversation_run",
            source_ref=f"run:{run_id}",
            metadata={
                "run_id": run_id,
                "source": source,
                "intent": intent,
                "q_crystal": q_crystal,
                "stability": stability,
                "models": model_summary or {},
                "continuity": "semantic_candidate",
                "policy": "candidate_document_not_stable_memory",
            },
            status="candidate",
            document_id=f"run-sem-{run_id}",
        )
        embedding_event = self._embed_document(document.document_id, document.normalized_content)
        return {
            "status": "ok",
            "mode": "semantic-continuity",
            "document": document.to_dict(),
            "embedding_event": embedding_event,
            "policy": {
                "identity_core_modified": False,
                "auto_consolidation": False,
                "document_status": "candidate",
            },
        }

    def backfill_recent_runs(self, limit: int = 50) -> dict[str, Any]:
        rows = self._recent_runs(limit=limit)
        results = []
        for row in rows:
            results.append(
                self.ingest_run(
                    run_id=str(row["run_id"]),
                    user_input=str(row["user_input"] or ""),
                    response=str(row["summary"] or row["content"] or ""),
                    source=str(row["source"] or "unknown"),
                    intent=str(row["intent"] or "unknown"),
                    q_crystal=float(row["q_crystal"]) if row["q_crystal"] is not None else None,
                    stability=float(row["stability"]) if row["stability"] is not None else None,
                    model_summary={
                        "hypothalamus": row["model_hypothalamus"],
                        "central": row["model_central"],
                    },
                )
            )
        return {
            "status": "ok",
            "mode": "semantic-continuity-backfill",
            "requested_limit": limit,
            "processed": len(results),
            "documents_created_or_updated": len([item for item in results if item.get("document")]),
            "embeddings_ok": sum(1 for item in results if item.get("embedding_event", {}).get("ok")),
            "results": results,
        }

    def doctor(self) -> dict[str, Any]:
        store = self.store.doctor()
        run_docs = [
            document
            for document in self.store.list_documents(limit=1000)
            if str(document.get("source_type")) == "conversation_run"
        ]
        return {
            "status": "ok",
            "mode": "semantic-continuity",
            "store": store,
            "conversation_run_documents": len(run_docs),
            "policy": {
                "run_documents_status": "candidate",
                "auto_consolidation": False,
                "identity_core_modified": False,
                "local_hash_embedding_fallback": True,
            },
        }

    def _embed_document(self, document_id: str, normalized_content: str) -> dict[str, Any]:
        if self.auto_ollama_embed:
            event = SemanticEmbeddingEngine(store=self.store).embed_document(document_id).to_dict()
            if event.get("ok"):
                return event
        vector = local_hash_embedding(normalized_content)
        stored = self.store.store_embedding(document_id, LOCAL_HASH_MODEL, vector, status="stored")
        return {
            "ok": True,
            "document_id": document_id,
            "model": LOCAL_HASH_MODEL,
            "dimensions": stored.dimensions,
            "status": "stored",
            "provider": "local",
            "embedding_id_stored": True,
            "model_selection_reason": "ollama_unavailable_or_not_required_local_continuity",
            "error": None,
        }

    def _recent_runs(self, limit: int) -> list[sqlite3.Row]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                """SELECT r.run_id, r.source, r.user_input, r.model_hypothalamus, r.model_central,
                e.content, e.summary, s.intent, c.q_crystal, c.stability
                FROM runs r
                LEFT JOIN episodic_memory e ON e.run_id = r.run_id
                LEFT JOIN signal_states s ON s.run_id = r.run_id
                LEFT JOIN crystal_states c ON c.run_id = r.run_id
                ORDER BY r.id DESC LIMIT ?""",
                (max(1, int(limit)),),
            ).fetchall()

    @staticmethod
    def _run_content(
        run_id: str,
        user_input: str,
        response: str,
        source: str,
        intent: str,
        q_crystal: float | None,
        stability: float | None,
    ) -> str:
        return "\n".join(
            [
                f"run_id: {run_id}",
                f"source: {source}",
                f"intent: {intent}",
                f"q_crystal: {q_crystal}",
                f"stability: {stability}",
                f"user_input: {user_input}",
                f"response_summary: {response[:1200]}",
            ]
        )


def local_hash_embedding(text: str, dimensions: int = 64) -> list[float]:
    vector = [0.0 for _ in range(dimensions)]
    words = [word.strip(".,:;!?¡¿()[]{}\"'").lower() for word in text.split()]
    for word in [word for word in words if word]:
        digest = hashlib.sha256(word.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        vector[0] = 1.0
        return vector
    return [round(value / norm, 8) for value in vector]

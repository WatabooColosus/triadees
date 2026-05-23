"""Gobierno de memoria semántica · Tríade Ω 1.9E.

Clasifica documentos vectoriales y controla cuáles pueden influir en el ciclo
cognitivo. Un match puede ser recuperado por similitud sin estar autorizado a
entrar como memoria confiable para Central.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from triade.core.contracts import MemoryPacket, utc_now

from .semantic_store import SemanticMemoryStore


@dataclass(slots=True)
class GovernanceDecision:
    document_id: str
    document_status: str
    decision: str
    allowed_to_influence: bool
    reason: str
    source_ref: str | None = None
    similarity: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SemanticMemoryGovernance:
    """Política de promoción e influencia de recuerdos semánticos."""

    VALID_STATUSES = {"candidate", "experimental", "stable", "rejected"}
    VALID_TRANSITIONS = {
        "candidate": {"experimental", "rejected"},
        "experimental": {"stable", "candidate", "rejected"},
        "stable": {"rejected"},
        "rejected": {"candidate"},
    }

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.store = SemanticMemoryStore(db_path=self.db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS semantic_governance_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL,
                    previous_status TEXT NOT NULL,
                    new_status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    approved_by TEXT NOT NULL,
                    evidence TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (document_id) REFERENCES semantic_documents(document_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_semantic_governance_document ON semantic_governance_events(document_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_semantic_governance_status ON semantic_governance_events(new_status)"
            )

    def transition_document(
        self,
        document_id: str,
        new_status: str,
        reason: str,
        approved_by: str = "human",
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target = new_status.strip().lower()
        clean_reason = reason.strip()
        document = self.store.get_document(document_id)
        if document is None:
            raise KeyError(f"No existe documento semántico: {document_id}")
        if target not in self.VALID_STATUSES:
            raise ValueError(f"Estado semántico inválido: {target}")
        if not clean_reason:
            raise ValueError("La transición requiere una razón verificable.")
        current = str(document.get("status") or "candidate")
        if target == current:
            raise ValueError(f"El documento ya está en estado {target}.")
        if target not in self.VALID_TRANSITIONS.get(current, set()):
            raise ValueError(f"Transición no permitida: {current} -> {target}")
        if target == "stable" and not document.get("source_ref"):
            raise ValueError("No se puede consolidar una memoria estable sin source_ref.")
        timestamp = utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE semantic_documents SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE document_id = ?",
                (target, document_id),
            )
            conn.execute(
                """INSERT INTO semantic_governance_events
                (document_id, previous_status, new_status, reason, approved_by, evidence, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    document_id,
                    current,
                    target,
                    clean_reason,
                    approved_by.strip() or "human",
                    json.dumps(evidence or {}, ensure_ascii=False),
                    timestamp,
                ),
            )
        updated = self.store.get_document(document_id) or {}
        return {
            "status": "ok",
            "document_id": document_id,
            "previous_status": current,
            "new_status": target,
            "reason": clean_reason,
            "approved_by": approved_by.strip() or "human",
            "document": updated,
        }

    def govern_memory(self, memory: MemoryPacket, allow_experimental: bool = False) -> MemoryPacket:
        if not memory.semantic_recall.get("enabled"):
            memory.semantic_recall["governance"] = {
                "enabled": True,
                "status": "not_required",
                "allowed_statuses": ["stable"],
                "allow_experimental": allow_experimental,
                "decisions": [],
            }
            return memory

        vector_matches = [
            match for match in memory.semantic_matches if match.get("retrieval_type") == "vector_similarity"
        ]
        legacy_matches = [
            match for match in memory.semantic_matches if match.get("retrieval_type") != "vector_similarity"
        ]
        allowed: list[dict[str, Any]] = []
        quarantined: list[dict[str, Any]] = []
        decisions: list[GovernanceDecision] = []
        allowed_statuses = {"stable"}
        if allow_experimental:
            allowed_statuses.add("experimental")

        for match in vector_matches:
            document_id = str(match.get("document_id", ""))
            document = self.store.get_document(document_id)
            status = str(document.get("status") if document else "missing")
            source_ref = document.get("source_ref") if document else match.get("source_ref")
            similarity = float(match.get("similarity")) if match.get("similarity") is not None else None
            enriched = {
                **match,
                "document_status": status,
                "source_ref": source_ref,
            }
            if status in allowed_statuses:
                decision = GovernanceDecision(
                    document_id=document_id,
                    document_status=status,
                    decision="allowed",
                    allowed_to_influence=True,
                    reason="Memoria autorizada por política de estado semántico.",
                    source_ref=source_ref,
                    similarity=similarity,
                )
                allowed.append(enriched)
            else:
                reason = {
                    "candidate": "Memoria candidata recuperada, pendiente de evaluación y promoción.",
                    "experimental": "Memoria experimental no autorizada en este run.",
                    "rejected": "Memoria rechazada y excluida de influencia.",
                    "missing": "Documento recuperado sin registro persistente verificable.",
                }.get(status, "Estado semántico no autorizado para influencia.")
                decision = GovernanceDecision(
                    document_id=document_id,
                    document_status=status,
                    decision="quarantined",
                    allowed_to_influence=False,
                    reason=reason,
                    source_ref=source_ref,
                    similarity=similarity,
                )
                quarantined.append(enriched)
            decisions.append(decision)

        memory.semantic_matches = allowed + legacy_matches
        memory.semantic_recall["governance"] = {
            "enabled": True,
            "status": "applied",
            "allowed_statuses": sorted(allowed_statuses),
            "allow_experimental": allow_experimental,
            "retrieved_vector_matches": len(vector_matches),
            "allowed_vector_matches": len(allowed),
            "quarantined_vector_matches": len(quarantined),
            "quarantined_matches": quarantined,
            "decisions": [decision.to_dict() for decision in decisions],
        }
        memory.semantic_recall["authorized_matches_count"] = len(allowed)
        return memory

    def list_events(self, document_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if document_id:
                rows = conn.execute(
                    "SELECT * FROM semantic_governance_events WHERE document_id = ? ORDER BY id DESC LIMIT ?",
                    (document_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM semantic_governance_events ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            try:
                item["evidence"] = json.loads(item.get("evidence") or "{}")
            except json.JSONDecodeError:
                item["evidence"] = {}
            results.append(item)
        return results

    def doctor(self) -> dict[str, Any]:
        documents = self.store.list_documents(limit=1000)
        counts: dict[str, int] = {status: 0 for status in sorted(self.VALID_STATUSES)}
        for document in documents:
            status = str(document.get("status") or "candidate")
            counts[status] = counts.get(status, 0) + 1
        return {
            "status": "ok",
            "mode": "semantic-memory-governance-1.9E",
            "policy": {
                "default_allowed_statuses": ["stable"],
                "experimental_requires_explicit_authorization": True,
                "candidate_can_influence": False,
                "rejected_can_influence": False,
            },
            "documents_by_status": counts,
            "recent_events": self.list_events(limit=10),
        }

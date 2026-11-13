"""Gobierno de memoria semántica de Tríade Ω 1.9E."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, ClassVar

from triade.core.contracts import MemoryPacket, utc_now
from triade.db import sqlite3

from .semantic_store import SemanticMemoryStore

#: Política canónica 1.9E de influencia por estado semántico:
#: `stable` influye por defecto; `experimental` sólo si el run lo autoriza
#: explícitamente; `candidate` y `rejected` nunca.
#:
#: Vive aquí y sólo aquí. Cualquier canal de recuperación que decida qué puede
#: influir —el vectorial y el de palabras clave de `Bodega`— llama a esta
#: función en vez de repetir la lista: dos copias de la regla es la forma en que
#: un canal se queda atrás y deja pasar lo que el otro bloquea.
DEFAULT_INFLUENCE_STATUSES: frozenset[str] = frozenset({"stable"})
AUTHORIZED_INFLUENCE_STATUS = "experimental"


def influence_allowed_statuses(allow_experimental: bool = False) -> set[str]:
    """Estados que pueden influir en un run, según lo que el run autorice."""
    if allow_experimental:
        return {*DEFAULT_INFLUENCE_STATUSES, AUTHORIZED_INFLUENCE_STATUS}
    return set(DEFAULT_INFLUENCE_STATUSES)


@dataclass(slots=True)
class GovernanceDecision:
    document_id: str
    document_status: str
    decision: str
    allowed_to_influence: bool
    reason: str
    source_ref: str | None = None
    similarity: float | None = None
    channel: str = "vector_similarity"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SemanticMemoryGovernance:
    VALID_STATUSES: ClassVar = {"candidate", "experimental", "stable", "rejected"}
    VALID_TRANSITIONS: ClassVar = {
        "candidate": {"experimental", "rejected"},
        "experimental": {"stable", "candidate", "rejected"},
        "stable": {"rejected"},
        "rejected": {"candidate"},
    }
    VECTOR_CONFIDENCE_BOOST = 0.20

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.store = SemanticMemoryStore(db_path=self.db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS semantic_governance_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL,
                previous_status TEXT NOT NULL, new_status TEXT NOT NULL,
                reason TEXT NOT NULL, approved_by TEXT NOT NULL, evidence TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES semantic_documents(document_id) ON DELETE CASCADE)""")
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
        target, clean_reason = new_status.strip().lower(), reason.strip()
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
            raise ValueError(
                "No se puede consolidar una memoria estable sin source_ref."
            )
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
                    utc_now(),
                ),
            )
        return {
            "status": "ok",
            "document_id": document_id,
            "previous_status": current,
            "new_status": target,
            "reason": clean_reason,
            "approved_by": approved_by.strip() or "human",
            "document": self.store.get_document(document_id) or {},
        }

    def _judge(
        self, match: dict[str, Any], allowed_statuses: set[str], channel: str
    ) -> tuple[dict[str, Any], bool, dict[str, Any]]:
        """Decide si un recuerdo recuperado puede influir, mire por donde mire.

        El estado lo manda el documento en la base, no lo que traiga el match:
        un recuerdo que llegue sin `document_id` —o cuyo documento ya no exista—
        se queda en `missing` y por tanto fuera de `allowed_statuses`.
        """
        doc_id = str(match.get("document_id", ""))
        document = self.store.get_document(doc_id) if doc_id else None
        state = str(document.get("status") if document else "missing")
        source = document.get("source_ref") if document else match.get("source_ref")
        enriched = {**match, "document_status": state, "source_ref": source}
        allowed = state in allowed_statuses
        reason = (
            "Memoria autorizada por estado semántico."
            if allowed
            else "Memoria recuperada sin autorización de influencia; requiere promoción verificable."
        )
        raw_similarity = match.get("similarity")
        similarity = float(raw_similarity) if raw_similarity is not None else None
        enriched["allowed_to_influence"] = allowed
        decision = GovernanceDecision(
            doc_id,
            state,
            "allowed" if allowed else "quarantined",
            allowed,
            reason,
            source,
            similarity,
            channel,
        )
        return enriched, allowed, decision.to_dict()

    def govern_memory(
        self, memory: MemoryPacket, allow_experimental: bool = False
    ) -> MemoryPacket:
        allowed_statuses = influence_allowed_statuses(allow_experimental)
        if not memory.semantic_recall.get("enabled"):
            memory.semantic_recall["governance"] = {
                "enabled": True,
                "status": "not_required",
                "allowed_statuses": sorted(allowed_statuses),
                "allow_experimental": allow_experimental,
                "decisions": [],
            }
            return memory
        vector = [
            m
            for m in memory.semantic_matches
            if m.get("retrieval_type") == "vector_similarity"
        ]
        keyword = [
            m
            for m in memory.semantic_matches
            if m.get("retrieval_type") != "vector_similarity"
        ]
        accepted: list[dict[str, Any]] = []
        held: list[dict[str, Any]] = []
        keyword_accepted: list[dict[str, Any]] = []
        keyword_held: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        for match in vector:
            enriched, allowed, decision = self._judge(
                match, allowed_statuses, "vector_similarity"
            )
            (accepted if allowed else held).append(enriched)
            decisions.append(decision)
        # El canal de palabras clave pasa por el **mismo** gate. Antes se
        # anotaba `legacy_keyword_no_governance` con `allowed_to_influence=True`
        # sin mirar el estado: bastaba con recuperar por texto para influir.
        for match in keyword:
            enriched, allowed, decision = self._judge(
                match, allowed_statuses, "keyword"
            )
            (keyword_accepted if allowed else keyword_held).append(enriched)
            decisions.append(decision)
        confidence_before, removed = memory.confidence, 0.0
        if vector and not accepted:
            removed = self.VECTOR_CONFIDENCE_BOOST
            memory.confidence = round(max(0.0, memory.confidence - removed), 2)
        memory.semantic_matches = accepted + keyword_accepted
        memory.semantic_recall["authorized_matches_count"] = len(accepted) + len(
            keyword_accepted
        )
        memory.semantic_recall["governance"] = {
            "enabled": True,
            "status": "applied",
            "allowed_statuses": sorted(allowed_statuses),
            "allow_experimental": allow_experimental,
            "retrieved_vector_matches": len(vector),
            "allowed_vector_matches": len(accepted),
            "quarantined_vector_matches": len(held),
            "retrieved_keyword_matches": len(keyword),
            "allowed_keyword_matches": len(keyword_accepted),
            "quarantined_keyword_matches": len(keyword_held),
            "quarantined_matches": held + keyword_held,
            "decisions": decisions,
            "confidence_before_governance": confidence_before,
            "confidence_after_governance": memory.confidence,
            "removed_confidence_boost": removed,
        }
        return memory

    def list_events(
        self, document_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
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
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["evidence"] = json.loads(item.get("evidence") or "{}")
            except json.JSONDecodeError:
                item["evidence"] = {}
            result.append(item)
        return result

    def doctor(self) -> dict[str, Any]:
        counts = {state: 0 for state in sorted(self.VALID_STATUSES)}
        for document in self.store.list_documents(limit=1000):
            state = str(document.get("status") or "candidate")
            counts[state] = counts.get(state, 0) + 1
        return {
            "status": "ok",
            "mode": "semantic-memory-governance-1.9E",
            "policy": {
                "default_allowed_statuses": ["stable"],
                "experimental_requires_explicit_authorization": True,
                "candidate_can_influence": False,
                "rejected_can_influence": False,
                "quarantined_memory_increases_confidence": False,
            },
            "documents_by_status": counts,
            "recent_events": self.list_events(limit=10),
        }

"""Causal provenance and one-shot consumption governance for evidence."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, model_validator

OriginClass = Literal[
    "human", "external_system", "trusted_federated", "autonomous", "derived"
]
EXTERNAL_ORIGINS = {"human", "external_system", "trusted_federated"}


class EvidenceRecord(BaseModel):
    evidence_id: str
    origin_class: OriginClass
    producer_id: str
    source: str
    root_external_event_id: str | None = None
    causal_parent_id: str | None = None
    autonomous_depth: int = 0
    content_hash: str
    created_at: str
    trust_level: str
    verification_status: str

    @model_validator(mode="after")
    def validate_causality(self) -> EvidenceRecord:
        if self.origin_class == "autonomous" and self.root_external_event_id:
            raise ValueError("autonomous_evidence_cannot_claim_external_root")
        if self.origin_class == "derived" and not self.causal_parent_id:
            raise ValueError("derived_evidence_requires_parent")
        if self.autonomous_depth < 0:
            raise ValueError("autonomous_depth_must_be_nonnegative")
        return self

    @property
    def independently_external(self) -> bool:
        return self.origin_class in EXTERNAL_ORIGINS and self.autonomous_depth == 0


class EvidenceProvenanceStore:
    def __init__(self, db_path: str | Path, *, max_autonomous_depth: int = 8) -> None:
        self.db_path = Path(db_path)
        self.max_autonomous_depth = max_autonomous_depth
        migration = (
            Path(__file__).resolve().parents[1]
            / "memory/migrations/016_evidence_provenance.sql"
        )
        with closing(self._connect()) as conn, conn:
            conn.executescript(migration.read_text(encoding="utf-8"))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def create(
        self,
        *,
        origin_class: OriginClass,
        producer_id: str,
        source: str,
        content: bytes | str,
        trust_level: str = "candidate",
        verification_status: str = "unverified",
        causal_parent_id: str | None = None,
        root_external_event_id: str | None = None,
        created_at: str | None = None,
    ) -> EvidenceRecord:
        evidence_id = f"evidence-{uuid4().hex}"
        depth = 0
        if origin_class == "derived":
            parent = self.get(str(causal_parent_id or ""))
            if parent is None:
                raise ValueError("derived_evidence_parent_not_found")
            depth = parent.autonomous_depth + 1
            root_external_event_id = parent.root_external_event_id
        elif origin_class == "autonomous":
            depth = 1
            root_external_event_id = None
        elif origin_class in EXTERNAL_ORIGINS:
            root_external_event_id = root_external_event_id or evidence_id
        if depth > self.max_autonomous_depth:
            raise ValueError("autonomous_depth_limit_exceeded")
        raw = content.encode() if isinstance(content, str) else content
        record = EvidenceRecord(
            evidence_id=evidence_id,
            origin_class=origin_class,
            producer_id=producer_id,
            source=source,
            root_external_event_id=root_external_event_id,
            causal_parent_id=causal_parent_id,
            autonomous_depth=depth,
            content_hash=hashlib.sha256(raw).hexdigest(),
            created_at=created_at or datetime.now(UTC).isoformat(),
            trust_level=trust_level,
            verification_status=verification_status,
        )
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO governed_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                tuple(record.model_dump().values()),
            )
        return record

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT * FROM governed_evidence WHERE evidence_id=?", (evidence_id,)
            ).fetchone()
        return EvidenceRecord.model_validate(dict(row)) if row else None

    def consume(
        self,
        evidence_id: str,
        *,
        consumer_type: str,
        consumer_id: str,
        task_id: str | None = None,
        outcome: str = "accepted",
    ) -> bool:
        if self.get(evidence_id) is None:
            raise KeyError("evidence_not_found")
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    "INSERT INTO evidence_consumptions VALUES(?,?,?,?,?,?)",
                    (
                        evidence_id,
                        consumer_type,
                        consumer_id,
                        task_id,
                        datetime.now(UTC).isoformat(),
                        outcome,
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def can_wake_neuron(self, evidence_id: str, *, last_cycle_at: str) -> bool:
        evidence = self.get(evidence_id)
        if evidence is None or not evidence.independently_external:
            return False
        created = datetime.fromisoformat(evidence.created_at)
        last_cycle = datetime.fromisoformat(last_cycle_at)
        return (
            created > last_cycle
            and evidence.autonomous_depth <= self.max_autonomous_depth
        )

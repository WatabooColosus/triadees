"""Research runs gobernados con fuentes independientes y candidate-only."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlparse

from triade.learning.pipeline import LearningPipeline

SCHEMA = Path(__file__).resolve().parent.parent / "memory/schemas.sql"
MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "memory/migrations/024_governed_research.sql"
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class GovernedResearchWorker:
    TRIGGERS: ClassVar[set[str]] = {
        "gap",
        "contradiction",
        "repeated_failure",
        "benchmark_need",
        "human_decision",
    }

    def __init__(
        self,
        db_path: str | Path,
        provider: Callable[[str, int], dict[str, Any]],
    ) -> None:
        self.db_path = Path(db_path)
        self.provider = provider
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA.read_text(encoding="utf-8"))
            conn.executescript(MIGRATION.read_text(encoding="utf-8"))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def run(
        self,
        *,
        question: str,
        trigger: str,
        scope: str,
        allowed_sources: list[str],
        minimum_independent_sources: int = 2,
        unresolved_questions: list[str] | None = None,
    ) -> dict[str, Any]:
        if trigger not in self.TRIGGERS:
            raise ValueError(f"trigger no gobernado: {trigger}")
        if not question.strip() or not scope.strip() or not allowed_sources:
            raise ValueError("question, scope y allowed_sources son obligatorios")
        if minimum_independent_sources < 2:
            raise ValueError("minimum_independent_sources debe ser >= 2")
        raw = self.provider(question, minimum_independent_sources)
        failures = [dict(item) for item in raw.get("failures", [])]
        accepted: list[dict[str, Any]] = []
        seen_independence: set[tuple[str, str]] = set()
        for source in raw.get("sources", []):
            url = str(source.get("url") or "")
            parsed = urlparse(url)
            host = parsed.hostname or ""
            content = str(source.get("content") or source.get("excerpt") or "").strip()
            source_type = str(source.get("source_type") or "web")
            if not source.get("accessible", True):
                failures.append({"url": url, "reason": "source_inaccessible"})
                continue
            if source_type in {"system_generated", "self_generated"}:
                failures.append(
                    {"url": url, "reason": "not_independent_system_content"}
                )
                continue
            if not host or not any(
                host == allowed or host.endswith(f".{allowed}")
                for allowed in allowed_sources
            ):
                failures.append({"url": url, "reason": "source_not_allowed"})
                continue
            if not content:
                failures.append({"url": url, "reason": "empty_source"})
                continue
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            identity = (host, content_hash)
            if identity in seen_independence or any(
                item["host"] == host for item in accepted
            ):
                failures.append({"url": url, "reason": "duplicate_not_independent"})
                continue
            seen_independence.add(identity)
            accepted.append(
                {
                    "url": url,
                    "title": str(source.get("title") or url),
                    "host": host,
                    "content_hash": content_hash,
                    "fetched_at": str(source.get("fetched_at") or _now()),
                    "claims": [dict(claim) for claim in source.get("claims", [])],
                    "provenance": {
                        "provider": str(source.get("provider") or "injected"),
                        "url": url,
                    },
                    "content": content,
                }
            )
        claims = [
            {**claim, "source_url": source["url"]}
            for source in accepted
            for claim in source["claims"]
        ]
        values_by_key: dict[str, set[str]] = {}
        for claim in claims:
            key = str(claim.get("key") or claim.get("claim") or "").strip()
            value = str(claim.get("value") or "").strip()
            if key:
                values_by_key.setdefault(key, set()).add(value)
        contradictions = [
            {"claim_key": key, "values": sorted(values), "resolution": "unresolved"}
            for key, values in values_by_key.items()
            if len(values) > 1
        ]
        independent = len(accepted)
        if independent < minimum_independent_sources:
            status = "insufficient_sources"
        elif contradictions:
            status = "conflicting_sources"
        elif not claims:
            status = "unverifiable"
        else:
            status = "candidate_created"
        confidence = min(0.95, independent / max(minimum_independent_sources, 1) * 0.7)
        candidate_id: str | None = None
        if status == "candidate_created":
            content = "\n\n".join(
                f"Fuente: {source['url']}\n{source['content']}" for source in accepted
            )
            candidate = LearningPipeline(self.db_path).ingest(
                content=content,
                source_type="web",
                source_ref=f"research:{question}",
                title=f"Research candidate: {question[:80]}",
                domain=scope,
                risk_level="low",
            )
            candidate_id = str(candidate.get("candidate_id") or "") or None
        research_id = f"gr-{uuid.uuid4().hex}"
        evidence_bundle = {
            "research_id": research_id,
            "question": question,
            "source_hashes": [source["content_hash"] for source in accepted],
            "source_count": independent,
            "candidate_only": True,
        }
        result = {
            "research_id": research_id,
            "question": question,
            "trigger": trigger,
            "scope": scope,
            "allowed_sources": allowed_sources,
            "minimum_independent_sources": minimum_independent_sources,
            "status": status,
            "sources": accepted,
            "source_failures": failures,
            "claims": claims,
            "contradictions": contradictions,
            "unresolved_questions": unresolved_questions or [],
            "confidence": confidence,
            "evidence_bundle": evidence_bundle,
            "candidate_id": candidate_id,
            "learning_validated": False,
            "stable_memory_written": False,
        }
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO governed_research_runs VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    research_id,
                    question,
                    trigger,
                    scope,
                    json.dumps(allowed_sources),
                    minimum_independent_sources,
                    status,
                    json.dumps(accepted),
                    json.dumps(failures),
                    json.dumps(claims),
                    json.dumps(contradictions),
                    json.dumps(unresolved_questions or []),
                    confidence,
                    json.dumps(evidence_bundle),
                    candidate_id,
                    _now(),
                ),
            )
        return result

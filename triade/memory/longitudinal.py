"""Memoria longitudinal gobernada, explicable y aislada por tenant."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import sqlite3
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

MIGRATION = Path(__file__).resolve().parent / "migrations/021_longitudinal_memory.sql"
SCHEMA = Path(__file__).resolve().parent / "schemas.sql"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _normalize(value: str) -> str:
    plain = unicodedata.normalize("NFKD", value.strip().lower())
    return " ".join(plain.encode("ascii", "ignore").decode("ascii").split())


@dataclass(frozen=True, slots=True)
class MemoryScope:
    user_id: str
    session_id: str = ""
    project_id: str = ""
    domain: str = "general"

    def validate(self) -> None:
        if not self.user_id.strip():
            raise ValueError("user_id es obligatorio para aislar memoria")


@dataclass(frozen=True, slots=True)
class MemoryObservation:
    memory_type: str
    key: str
    value: str
    source_ref: str
    source_type: str = "conversation"
    confidence: float = 0.7
    valid_from: str | None = None
    valid_until: str | None = None
    expires_at: str | None = None


class LongitudinalMemory:
    TYPES: ClassVar[set[str]] = {
        "fact",
        "preference",
        "correction",
        "relationship",
        "decision",
        "restriction",
        "project",
        "temporal",
    }
    STATES: ClassVar[set[str]] = {
        "observed",
        "candidate",
        "verified",
        "stable",
        "contradicted",
        "expired",
        "quarantined",
    }
    TRANSITIONS: ClassVar[dict[str, set[str]]] = {
        "observed": {"candidate", "quarantined"},
        "candidate": {"verified", "contradicted", "quarantined", "expired"},
        "verified": {"stable", "contradicted", "quarantined", "expired"},
        "stable": {"contradicted", "quarantined", "expired"},
        "contradicted": {"quarantined"},
        "expired": {"candidate", "quarantined"},
        "quarantined": {"candidate"},
    }

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA.read_text(encoding="utf-8"))
            conn.executescript(MIGRATION.read_text(encoding="utf-8"))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def extract(text: str, source_ref: str) -> list[MemoryObservation]:
        """Extrae categorías explícitas sin usar inferencia generativa."""
        patterns = (
            ("preference", r"^(?:prefiero|preference:)\s+(.+)$"),
            ("correction", r"^(?:correcci[oó]n:|correction:)\s+(.+)$"),
            ("relationship", r"^(?:relaci[oó]n:|relationship:)\s+(.+)$"),
            ("decision", r"^(?:decidimos|decisi[oó]n:|decision:)\s+(.+)$"),
            ("restriction", r"^(?:restricci[oó]n:|restriction:)\s+(.+)$"),
            ("project", r"^(?:proyecto:|project:)\s+(.+)$"),
            ("temporal", r"^(?:temporal:|desde|hasta)\s+(.+)$"),
            ("fact", r"^(?:hecho:|fact:)\s+(.+)$"),
        )
        observations: list[MemoryObservation] = []
        for raw in re.split(r"[\n;]+", text):
            sentence = raw.strip()
            for memory_type, pattern in patterns:
                match = re.match(pattern, sentence, flags=re.IGNORECASE)
                if not match:
                    continue
                content = match.group(1).strip()
                key, separator, value = content.partition("=")
                if not separator:
                    key, separator, value = content.partition(":")
                if separator and key.strip() and value.strip():
                    observations.append(
                        MemoryObservation(
                            memory_type=memory_type,
                            key=_normalize(key).replace(" ", "_"),
                            value=value.strip(),
                            source_ref=source_ref,
                        )
                    )
                break
        return observations

    def observe(
        self,
        observation: MemoryObservation,
        scope: MemoryScope,
        *,
        initial_status: str = "candidate",
    ) -> dict[str, Any]:
        scope.validate()
        if observation.memory_type not in self.TYPES:
            raise ValueError(f"Tipo de memoria inválido: {observation.memory_type}")
        if initial_status not in {"observed", "candidate"}:
            raise ValueError("Una observación solo puede iniciar observed o candidate")
        if not observation.key.strip() or not observation.value.strip():
            raise ValueError("key y value son obligatorios")
        if not observation.source_ref.strip():
            raise ValueError("source_ref es obligatorio")
        normalized = _normalize(observation.value)
        now = _now()
        memory_id = f"lm-{uuid.uuid4().hex}"
        contradiction: sqlite3.Row | None = None
        with self._connect() as conn:
            contradiction = conn.execute(
                """SELECT * FROM longitudinal_memories
                WHERE user_id = ? AND project_id = ? AND domain = ?
                  AND memory_key = ? AND memory_type = ?
                  AND status IN ('candidate', 'verified', 'stable')
                  AND normalized_value != ?
                ORDER BY updated_at DESC LIMIT 1""",
                (
                    scope.user_id,
                    scope.project_id,
                    scope.domain,
                    observation.key,
                    observation.memory_type,
                    normalized,
                ),
            ).fetchone()
            contradiction_id = (
                str(contradiction["memory_id"]) if contradiction else None
            )
            if contradiction:
                conflicting_id = str(contradiction["memory_id"])
                conn.execute(
                    """UPDATE longitudinal_memories
                    SET status = 'contradicted', updated_at = ?, review_reason = ?
                    WHERE memory_id = ?""",
                    (now, f"superseded_by:{memory_id}", conflicting_id),
                )
                self._event(
                    conn,
                    conflicting_id,
                    "contradiction_detected",
                    str(contradiction["status"]),
                    "contradicted",
                    "longitudinal-memory",
                    "Conflicting value observed in identical scope and key.",
                    observation.source_ref,
                )
            conn.execute(
                """INSERT INTO longitudinal_memories
                (memory_id, memory_type, memory_key, memory_value, normalized_value,
                 status, user_id, session_id, project_id, domain, source_ref,
                 source_type, observed_at, valid_from, valid_until, expires_at,
                 confidence, supersedes_id, contradiction_of_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    memory_id,
                    observation.memory_type,
                    observation.key,
                    observation.value,
                    normalized,
                    initial_status,
                    scope.user_id,
                    scope.session_id,
                    scope.project_id,
                    scope.domain,
                    observation.source_ref,
                    observation.source_type,
                    now,
                    observation.valid_from,
                    observation.valid_until,
                    observation.expires_at,
                    max(0.0, min(1.0, observation.confidence)),
                    contradiction_id,
                    contradiction_id,
                    now,
                    now,
                ),
            )
            self._event(
                conn,
                memory_id,
                "observed",
                None,
                initial_status,
                observation.source_type,
                "Provenanced observation stored as non-stable memory.",
                observation.source_ref,
            )
        return {
            "memory_id": memory_id,
            "status": initial_status,
            "contradiction_detected": contradiction is not None,
            "contradiction_of_id": contradiction_id,
        }

    def transition(
        self,
        memory_id: str,
        new_status: str,
        *,
        actor: str,
        reason: str,
        evidence_ref: str,
    ) -> dict[str, Any]:
        if not actor.strip() or not reason.strip() or not evidence_ref.strip():
            raise ValueError("actor, reason y evidence_ref son obligatorios")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM longitudinal_memories WHERE memory_id = ?", (memory_id,)
            ).fetchone()
            if row is None:
                raise KeyError(memory_id)
            previous = str(row["status"])
            if new_status not in self.TRANSITIONS.get(previous, set()):
                raise ValueError(f"Transición inválida: {previous} -> {new_status}")
            conn.execute(
                """UPDATE longitudinal_memories SET status = ?, review_reason = ?,
                updated_at = ? WHERE memory_id = ?""",
                (new_status, reason, _now(), memory_id),
            )
            self._event(
                conn,
                memory_id,
                "status_transition",
                previous,
                new_status,
                actor,
                reason,
                evidence_ref,
            )
        return {
            "memory_id": memory_id,
            "previous_status": previous,
            "status": new_status,
        }

    def expire(self, at: str | None = None) -> list[str]:
        cutoff = at or _now()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT memory_id, status FROM longitudinal_memories
                WHERE expires_at IS NOT NULL AND expires_at <= ?
                  AND status IN ('candidate', 'verified', 'stable')""",
                (cutoff,),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE longitudinal_memories SET status = 'expired', updated_at = ? WHERE memory_id = ?",
                    (cutoff, row["memory_id"]),
                )
                self._event(
                    conn,
                    str(row["memory_id"]),
                    "expired",
                    str(row["status"]),
                    "expired",
                    "longitudinal-memory",
                    "expires_at reached",
                    str(row["memory_id"]),
                )
        return [str(row["memory_id"]) for row in rows]

    def apply_decay(
        self,
        *,
        at: str | None = None,
        half_life_days: float = 90.0,
        expiration_floor: float = 0.20,
    ) -> list[dict[str, Any]]:
        if half_life_days <= 0:
            raise ValueError("half_life_days debe ser positivo")
        effective_at = datetime.fromisoformat(at) if at else datetime.now(UTC)
        if effective_at.tzinfo is None:
            effective_at = effective_at.replace(tzinfo=UTC)
        changed: list[dict[str, Any]] = []
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT memory_id, status, confidence, updated_at
                FROM longitudinal_memories
                WHERE status IN ('candidate', 'verified')"""
            ).fetchall()
            for row in rows:
                updated = datetime.fromisoformat(str(row["updated_at"]))
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=UTC)
                age_days = max(0.0, (effective_at - updated).total_seconds() / 86400)
                previous = float(row["confidence"])
                current = max(0.0, previous * math.pow(0.5, age_days / half_life_days))
                status = "expired" if current < expiration_floor else str(row["status"])
                conn.execute(
                    """UPDATE longitudinal_memories
                    SET confidence = ?, status = ?, updated_at = ? WHERE memory_id = ?""",
                    (current, status, effective_at.isoformat(), row["memory_id"]),
                )
                self._event(
                    conn,
                    str(row["memory_id"]),
                    "confidence_decay",
                    str(row["status"]),
                    status,
                    "longitudinal-memory",
                    f"confidence:{previous:.8f}->{current:.8f};half_life_days:{half_life_days}",
                    str(row["memory_id"]),
                )
                changed.append(
                    {
                        "memory_id": str(row["memory_id"]),
                        "previous_confidence": previous,
                        "confidence": current,
                        "status": status,
                    }
                )
        return changed

    def recall(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 10,
        include_session: bool = True,
    ) -> list[dict[str, Any]]:
        scope.validate()
        self.expire()
        terms = [
            _normalize(term) for term in query.split() if len(_normalize(term)) >= 3
        ]
        session_clause = (
            "session_id IN ('', ?)" if include_session else "session_id = ''"
        )
        params: tuple[object, ...] = (
            (scope.user_id, scope.project_id, scope.domain, scope.session_id)
            if include_session
            else (scope.user_id, scope.project_id, scope.domain)
        )
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT * FROM longitudinal_memories
                WHERE user_id = ? AND project_id = ? AND domain = ?
                  AND status IN ('verified', 'stable')
                  AND {session_clause}
                ORDER BY confidence DESC, updated_at DESC""",
                params,
            ).fetchall()
        matches: list[dict[str, Any]] = []
        for row in rows:
            searchable = _normalize(
                f"{row['memory_key']} {row['memory_value']} {row['memory_type']}"
            )
            matched = sorted({term for term in terms if term in searchable})
            if terms and not matched:
                continue
            item = dict(row)
            item["why_retrieved"] = {
                "matched_terms": matched,
                "scope": asdict(scope),
                "status_gate": str(row["status"]),
                "source_ref": str(row["source_ref"]),
                "ranking": "confidence_desc_then_updated_at_desc",
            }
            matches.append(item)
            if len(matches) >= limit:
                break
        return matches

    def semantic_fingerprint(self) -> str:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT memory_id, memory_type, memory_key, memory_value, status,
                user_id, session_id, project_id, domain, source_ref, expires_at,
                supersedes_id, contradiction_of_id
                FROM longitudinal_memories ORDER BY memory_id"""
            ).fetchall()
        payload = json.dumps(
            [dict(row) for row in rows], sort_keys=True, ensure_ascii=False
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def backup(self, target: str | Path) -> dict[str, Any]:
        destination = Path(target)
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as source, sqlite3.connect(destination) as dest:
            source.backup(dest)
        return {"path": str(destination), "fingerprint": self.semantic_fingerprint()}

    @classmethod
    def restore_to_sandbox(
        cls, backup_path: str | Path, target: str | Path, expected_fingerprint: str
    ) -> dict[str, Any]:
        source, destination = Path(backup_path), Path(target)
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        restored = cls(destination)
        with sqlite3.connect(destination) as conn:
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        fingerprint = restored.semantic_fingerprint()
        return {
            "status": "verified"
            if integrity == "ok" and fingerprint == expected_fingerprint
            else "failed",
            "sqlite_integrity": integrity,
            "fingerprint": fingerprint,
            "expected_fingerprint": expected_fingerprint,
            "production_overwritten": False,
        }

    @staticmethod
    def _event(
        conn: sqlite3.Connection,
        memory_id: str,
        event_type: str,
        previous_status: str | None,
        new_status: str | None,
        actor: str,
        reason: str,
        evidence_ref: str | None,
    ) -> None:
        conn.execute(
            """INSERT INTO longitudinal_memory_events
            (event_id, memory_id, event_type, previous_status, new_status,
             actor, reason, evidence_ref, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"lme-{uuid.uuid4().hex}",
                memory_id,
                event_type,
                previous_status,
                new_status,
                actor,
                reason,
                evidence_ref,
                _now(),
            ),
        )

"""Memoria semántica persistente · Tríade Ω 1.9A/1.9E.

Almacena documentos y vectores; desde 1.9E protege el estado gobernado de un
documento para que una reingestión no degrade silenciosamente memoria aprobada.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


@dataclass(slots=True)
class SemanticDocument:
    document_id: str
    content: str
    normalized_content: str
    content_hash: str
    domain: str = "general"
    source_type: str = "manual"
    source_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "candidate"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SemanticEmbedding:
    document_id: str
    embedding_model: str
    vector: list[float]
    dimensions: int
    vector_norm: float
    status: str = "stored"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SemanticMemoryStore:
    """Almacén SQLite para documentos y embeddings semánticos."""

    VALID_DOCUMENT_STATUSES = {"candidate", "experimental", "stable", "rejected"}

    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        migration_path: str | Path = "triade/memory/migrations/001_9A_semantic_memory.sql",
    ) -> None:
        self.db_path = Path(db_path)
        self.migration_path = Path(migration_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        if not self.migration_path.exists():
            raise FileNotFoundError(f"No existe migración semántica: {self.migration_path}")
        with self._connect() as conn:
            conn.executescript(self.migration_path.read_text(encoding="utf-8"))

    def upsert_document(
        self,
        content: str,
        domain: str = "general",
        source_type: str = "manual",
        source_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "candidate",
        document_id: str | None = None,
    ) -> SemanticDocument:
        normalized = self.normalize_content(content)
        if not normalized:
            raise ValueError("El contenido semántico no puede estar vacío.")
        requested_status = status.strip().lower()
        if requested_status not in self.VALID_DOCUMENT_STATUSES:
            raise ValueError(f"Estado semántico inválido: {requested_status}")
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        requested_id = document_id or f"sem-{uuid4().hex[:16]}"
        metadata = metadata or {}
        effective_status = requested_status
        with self._connect() as conn:
            duplicate = conn.execute(
                "SELECT document_id, status FROM semantic_documents WHERE content_hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone()
            current = conn.execute(
                "SELECT document_id, content_hash, status FROM semantic_documents WHERE document_id = ? LIMIT 1",
                (requested_id,),
            ).fetchone()
            if duplicate and duplicate["document_id"] != requested_id:
                requested_id = str(duplicate["document_id"])
                effective_status = str(duplicate["status"] or "candidate")
            elif current:
                current_status = str(current["status"] or "candidate")
                if str(current["content_hash"]) != content_hash and current_status != "candidate":
                    raise ValueError(
                        "No se puede sobrescribir contenido de una memoria gobernada; cree un nuevo documento candidato."
                    )
                effective_status = current_status
            conn.execute(
                """
                INSERT INTO semantic_documents
                (document_id, content, normalized_content, content_hash, domain, source_type,
                 source_ref, metadata, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    content = excluded.content,
                    normalized_content = excluded.normalized_content,
                    content_hash = excluded.content_hash,
                    domain = excluded.domain,
                    source_type = excluded.source_type,
                    source_ref = excluded.source_ref,
                    metadata = excluded.metadata,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    requested_id,
                    content,
                    normalized,
                    content_hash,
                    domain.strip() or "general",
                    source_type.strip() or "manual",
                    source_ref,
                    json.dumps(metadata, ensure_ascii=False),
                    effective_status,
                ),
            )
        return SemanticDocument(
            document_id=requested_id,
            content=content,
            normalized_content=normalized,
            content_hash=content_hash,
            domain=domain.strip() or "general",
            source_type=source_type.strip() or "manual",
            source_ref=source_ref,
            metadata=metadata,
            status=effective_status,
        )

    def store_embedding(
        self,
        document_id: str,
        embedding_model: str,
        vector: Iterable[float],
        status: str = "stored",
    ) -> SemanticEmbedding:
        values = [float(value) for value in vector]
        if not values:
            raise ValueError("El vector de embedding no puede estar vacío.")
        if not embedding_model.strip():
            raise ValueError("Debe especificarse el modelo de embedding.")
        if not all(math.isfinite(value) for value in values):
            raise ValueError("El vector contiene valores no finitos.")
        norm = math.sqrt(sum(value * value for value in values))
        if norm <= 0:
            raise ValueError("El vector de embedding no puede tener norma cero.")
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT document_id FROM semantic_documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            if not exists:
                raise KeyError(f"No existe documento semántico: {document_id}")
            conn.execute(
                """
                INSERT INTO semantic_embeddings
                (document_id, embedding_model, vector_json, dimensions, vector_norm, status)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id, embedding_model) DO UPDATE SET
                    vector_json = excluded.vector_json,
                    dimensions = excluded.dimensions,
                    vector_norm = excluded.vector_norm,
                    status = excluded.status,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (document_id, embedding_model.strip(), json.dumps(values), len(values), norm, status),
            )
        return SemanticEmbedding(
            document_id=document_id,
            embedding_model=embedding_model.strip(),
            vector=values,
            dimensions=len(values),
            vector_norm=round(norm, 8),
            status=status,
        )

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM semantic_documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        return self._decode_document(dict(row)) if row else None

    def list_documents(self, limit: int = 20, domain: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if domain:
                rows = conn.execute(
                    "SELECT * FROM semantic_documents WHERE domain = ? ORDER BY id DESC LIMIT ?",
                    (domain, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM semantic_documents ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._decode_document(dict(row)) for row in rows]

    def list_embeddings(self, document_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if document_id:
                rows = conn.execute(
                    "SELECT * FROM semantic_embeddings WHERE document_id = ? ORDER BY id DESC",
                    (document_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM semantic_embeddings ORDER BY id DESC").fetchall()
        return [self._decode_embedding(dict(row)) for row in rows]

    def doctor(self) -> dict[str, Any]:
        with self._connect() as conn:
            documents = conn.execute("SELECT COUNT(*) AS c FROM semantic_documents").fetchone()["c"]
            embeddings = conn.execute("SELECT COUNT(*) AS c FROM semantic_embeddings").fetchone()["c"]
            pending = conn.execute(
                """SELECT COUNT(*) AS c FROM semantic_documents d
                WHERE NOT EXISTS (SELECT 1 FROM semantic_embeddings e WHERE e.document_id = d.document_id)"""
            ).fetchone()["c"]
            models = conn.execute(
                "SELECT embedding_model, COUNT(*) AS c FROM semantic_embeddings GROUP BY embedding_model ORDER BY c DESC"
            ).fetchall()
            status_rows = conn.execute(
                "SELECT status, COUNT(*) AS c FROM semantic_documents GROUP BY status ORDER BY status"
            ).fetchall()
        return {
            "status": "ok",
            "mode": "semantic-store-1.9E",
            "db_path": str(self.db_path),
            "documents": documents,
            "embeddings": embeddings,
            "documents_without_embedding": pending,
            "documents_by_status": [dict(row) for row in status_rows],
            "embedding_models": [dict(row) for row in models],
            "embedding_generation": "available_1.9B",
        }

    @staticmethod
    def normalize_content(content: str) -> str:
        return " ".join(str(content).strip().split())

    @staticmethod
    def _decode_document(row: dict[str, Any]) -> dict[str, Any]:
        try:
            row["metadata"] = json.loads(row.get("metadata") or "{}")
        except json.JSONDecodeError:
            row["metadata"] = {}
        return row

    @staticmethod
    def _decode_embedding(row: dict[str, Any]) -> dict[str, Any]:
        try:
            row["vector"] = json.loads(row.pop("vector_json", "[]"))
        except json.JSONDecodeError:
            row["vector"] = []
        return row

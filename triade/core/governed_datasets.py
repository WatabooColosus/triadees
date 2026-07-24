"""Governed Datasets & Trainable Adapters · Tríade Ω.

Gestiona datasets con reglas de gobernanza y adaptadores
entrenables vinculados a esos datasets.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass(slots=True)
class DatasetRecord:
    dataset_id: str
    name: str
    description: str
    domain: str
    source: str
    status: str
    row_count: int
    schema_json: dict[str, Any]
    governance_rules: dict[str, Any]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["schema_json"] = self.schema_json
        d["governance_rules"] = self.governance_rules
        return d


@dataclass(slots=True)
class AdapterRecord:
    adapter_id: str
    name: str
    base_model: str
    dataset_id: str | None
    status: str
    metrics: dict[str, Any]
    training_config: dict[str, Any]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["metrics"] = self.metrics
        d["training_config"] = self.training_config
        return d


class GovernedDatasets:
    """Almacén gobernado de datasets y adaptadores entrenables."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.schema_path = Path(__file__).resolve().parents[1] / "memory" / "schemas.sql"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        if self.schema_path.exists():
            with self._connect() as conn:
                conn.executescript(self.schema_path.read_text(encoding="utf-8"))

    # ── Dataset CRUD ──────────────────────────────────────────────────

    def create_dataset(
        self,
        name: str,
        description: str,
        domain: str = "general",
        source: str = "",
        governance_rules: dict[str, Any] | None = None,
    ) -> DatasetRecord:
        now = _utcnow()
        dataset_id = _new_id("ds")
        rules = governance_rules or {}
        record = DatasetRecord(
            dataset_id=dataset_id,
            name=name,
            description=description,
            domain=domain,
            source=source,
            status="draft",
            row_count=0,
            schema_json={},
            governance_rules=rules,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO governed_datasets
                    (dataset_id, name, description, domain, source, status,
                     row_count, schema_json, governance_rules, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.dataset_id,
                    record.name,
                    record.description,
                    record.domain,
                    record.source,
                    record.status,
                    record.row_count,
                    json.dumps(record.schema_json),
                    json.dumps(record.governance_rules),
                    record.created_at,
                    record.updated_at,
                ),
            )
        return record

    def get_dataset(self, dataset_id: str) -> DatasetRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM governed_datasets WHERE dataset_id = ?", (dataset_id,)
            ).fetchone()
        return self._row_to_dataset(row) if row else None

    def list_datasets(
        self, domain: str | None = None, status: str | None = None
    ) -> list[DatasetRecord]:
        query = "SELECT * FROM governed_datasets WHERE 1=1"
        params: list[Any] = []
        if domain:
            query += " AND domain = ?"
            params.append(domain)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_dataset(r) for r in rows]

    def update_dataset(
        self, dataset_id: str, updates: dict[str, Any]
    ) -> DatasetRecord | None:
        allowed = {"name", "description", "domain", "source", "row_count",
                    "schema_json", "governance_rules"}
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            return self.get_dataset(dataset_id)

        set_parts: list[str] = []
        params: list[Any] = []
        for k, v in filtered.items():
            if k in ("schema_json", "governance_rules"):
                set_parts.append(f"{k} = ?")
                params.append(json.dumps(v))
            else:
                set_parts.append(f"{k} = ?")
                params.append(v)
        set_parts.append("updated_at = ?")
        params.append(_utcnow())
        params.append(dataset_id)

        with self._connect() as conn:
            conn.execute(
                f"UPDATE governed_datasets SET {', '.join(set_parts)} WHERE dataset_id = ?",
                params,
            )
        return self.get_dataset(dataset_id)

    def archive_dataset(self, dataset_id: str) -> bool:
        now = _utcnow()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE governed_datasets SET status = 'archived', updated_at = ? WHERE dataset_id = ?",
                (now, dataset_id),
            )
        return cursor.rowcount > 0

    # ── Adapter CRUD ──────────────────────────────────────────────────

    def create_adapter(
        self,
        name: str,
        base_model: str,
        dataset_id: str | None = None,
        training_config: dict[str, Any] | None = None,
    ) -> AdapterRecord:
        now = _utcnow()
        adapter_id = _new_id("adapter")
        config = training_config or {}
        record = AdapterRecord(
            adapter_id=adapter_id,
            name=name,
            base_model=base_model,
            dataset_id=dataset_id,
            status="training",
            metrics={},
            training_config=config,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trainable_adapters
                    (adapter_id, name, base_model, dataset_id, status,
                     metrics, training_config, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.adapter_id,
                    record.name,
                    record.base_model,
                    record.dataset_id,
                    record.status,
                    json.dumps(record.metrics),
                    json.dumps(record.training_config),
                    record.created_at,
                    record.updated_at,
                ),
            )
        return record

    def update_adapter_status(
        self, adapter_id: str, status: str, metrics: dict[str, Any] | None = None
    ) -> AdapterRecord | None:
        valid = {"training", "trained", "evaluated", "deployed", "retired"}
        if status not in valid:
            raise ValueError(f"Estado inválido: {status}. Use: {valid}")
        now = _utcnow()
        with self._connect() as conn:
            if metrics is not None:
                conn.execute(
                    """
                    UPDATE trainable_adapters
                    SET status = ?, metrics = ?, updated_at = ?
                    WHERE adapter_id = ?
                    """,
                    (status, json.dumps(metrics), now, adapter_id),
                )
            else:
                conn.execute(
                    "UPDATE trainable_adapters SET status = ?, updated_at = ? WHERE adapter_id = ?",
                    (status, now, adapter_id),
                )
        return self.get_adapter(adapter_id)

    def get_adapter(self, adapter_id: str) -> AdapterRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM trainable_adapters WHERE adapter_id = ?", (adapter_id,)
            ).fetchone()
        return self._row_to_adapter(row) if row else None

    def list_adapters(
        self, status: str | None = None, base_model: str | None = None
    ) -> list[AdapterRecord]:
        query = "SELECT * FROM trainable_adapters WHERE 1=1"
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if base_model:
            query += " AND base_model = ?"
            params.append(base_model)
        query += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_adapter(r) for r in rows]

    # ── Governance ────────────────────────────────────────────────────

    def check_governance(self, dataset_id: str, intended_use: str) -> dict[str, Any]:
        dataset = self.get_dataset(dataset_id)
        if not dataset:
            return {"allowed": False, "reason": "Dataset no encontrado."}
        if dataset.status == "archived":
            return {"allowed": False, "reason": "Dataset archivado."}
        rules = dataset.governance_rules
        allowed_uses: list[str] = rules.get("allowed_uses", [])
        if allowed_uses and intended_use not in allowed_uses:
            return {
                "allowed": False,
                "reason": f"Uso '{intended_use}' no permitido. Permitidos: {allowed_uses}",
            }
        if rules.get("requires_consent") and not rules.get("consent_obtained"):
            return {"allowed": False, "reason": "Requiere consentimiento no obtenido."}
        return {"allowed": True, "reason": "Uso compatible con reglas de gobernanza."}

    def get_training_report(self, adapter_id: str) -> dict[str, Any]:
        adapter = self.get_adapter(adapter_id)
        if not adapter:
            return {"error": "Adaptador no encontrado."}

        recommendations: list[str] = []
        if adapter.status == "training":
            recommendations.append("Entrenamiento en curso. Monitorear métricas.")
        elif adapter.status == "trained":
            recommendations.append("Listo para evaluación. Ejecutar eval antes de deploy.")
        elif adapter.status == "evaluated":
            if adapter.metrics.get("accuracy", 0) < 0.7:
                recommendations.append("Accuracy baja. Considerar más datos o reentrenar.")
            recommendations.append("Aprobado para deployment.")
        elif adapter.status == "deployed":
            recommendations.append("En producción. Monitorear drift y latencia.")
        elif adapter.status == "retired":
            recommendations.append("Retirado. Considerar reemplazo con versión más reciente.")

        dataset_info: dict[str, Any] | None = None
        if adapter.dataset_id:
            ds = self.get_dataset(adapter.dataset_id)
            if ds:
                dataset_info = {
                    "dataset_id": ds.dataset_id,
                    "name": ds.name,
                    "domain": ds.domain,
                    "status": ds.status,
                    "governance_rules": ds.governance_rules,
                }

        return {
            "adapter_id": adapter.adapter_id,
            "name": adapter.name,
            "base_model": adapter.base_model,
            "status": adapter.status,
            "metrics": adapter.metrics,
            "training_config": adapter.training_config,
            "dataset": dataset_info,
            "recommendations": recommendations,
        }

    # ── Internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _row_to_dataset(row: sqlite3.Row) -> DatasetRecord:
        return DatasetRecord(
            dataset_id=row["dataset_id"],
            name=row["name"],
            description=row["description"],
            domain=row["domain"],
            source=row["source"],
            status=row["status"],
            row_count=row["row_count"],
            schema_json=json.loads(row["schema_json"] or "{}"),
            governance_rules=json.loads(row["governance_rules"] or "{}"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_adapter(row: sqlite3.Row) -> AdapterRecord:
        return AdapterRecord(
            adapter_id=row["adapter_id"],
            name=row["name"],
            base_model=row["base_model"],
            dataset_id=row["dataset_id"],
            status=row["status"],
            metrics=json.loads(row["metrics"] or "{}"),
            training_config=json.loads(row["training_config"] or "{}"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

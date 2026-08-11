"""Gate de integridad, dataset, canary, activación nominal y rollback PEFT."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triade.db import sqlite3

SCHEMA = Path(__file__).resolve().parent.parent / "memory/schemas.sql"
MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "memory/migrations/029_lora_serving_governance.sql"
)
#: Se aplica aparte porque `ALTER TABLE ADD COLUMN` no admite `IF NOT EXISTS` en
#: SQLite y este constructor corre en cada instanciación.
MIGRATION_BASE_MODEL = (
    Path(__file__).resolve().parent.parent / "memory/migrations/030_peft_base_model.sql"
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def normalize_model_id(model: str) -> str:
    """Reduce un identificador de modelo a una clave comparable entre proveedores.

    Un adaptador declara su base en formato HuggingFace
    (`Qwen/Qwen2.5-0.5B-Instruct`) y el runtime sirve etiquetas de Ollama
    (`qwen2.5:3b-instruct`). Sin una clave común no se puede responder a la única
    pregunta que importa antes de activar: ¿este adaptador es de este modelo?

    Se descarta la organización y se eliminan los separadores, que es lo único
    que varía entre proveedores: `Qwen/Qwen2.5-0.5B-Instruct` y
    `qwen2.5:0.5b-instruct` coinciden, `google/gemma-3-4b` y `gemma3:4b`
    también, y `qwen2.5:3b-instruct` no coincide con ninguno de los dos.

    Es deliberadamente estricta. Ante un nombre que no sepa reducir devuelve algo
    que no casará con nada, y `activate()` bloquea: para una puerta de seguridad,
    equivocarse hacia «no compatible» es el lado correcto.
    """
    texto = str(model or "").strip().lower()
    if not texto:
        return ""
    texto = texto.rpartition("/")[2]
    return re.sub(r"[^a-z0-9.]+", "", texto)


def build_integrity_bundle(adapter_path: str | Path) -> dict[str, Any]:
    root = Path(adapter_path).resolve()
    files = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.iterdir())
        if path.is_file() and path.name != "serving_integrity.json"
    }
    bundle: dict[str, Any] = {"files": files}
    bundle["bundle_sha256"] = hashlib.sha256(
        json.dumps(files, sort_keys=True).encode()
    ).hexdigest()
    (root / "serving_integrity.json").write_text(
        json.dumps(bundle, indent=2) + "\n", encoding="utf-8"
    )
    return bundle


class GovernedPeftServing:
    def __init__(
        self,
        db_path: str | Path,
        adapters_root: str | Path,
        served_models: Sequence[str] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.adapters_root = Path(adapters_root).resolve()
        #: Modelos que el runtime sirve de verdad. Si no se inyectan se
        #: preguntan a Ollama en el momento de activar, que es cuando importa.
        self.served_models = list(served_models) if served_models is not None else None
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA.read_text(encoding="utf-8"))
            conn.executescript(MIGRATION.read_text(encoding="utf-8"))
            columnas = {
                fila[1]
                for fila in conn.execute("PRAGMA table_info(governed_peft_versions)")
            }
            if "base_model" not in columnas:
                conn.executescript(MIGRATION_BASE_MODEL.read_text(encoding="utf-8"))

    def enroll(
        self, adapter_path: str | Path, *, traffic_percent: float = 5.0
    ) -> dict[str, Any]:
        if not 0 < traffic_percent <= 10:
            raise ValueError("canary_traffic_must_be_between_0_and_10")
        root, manifest, bundle = self._verify_blobs(adapter_path)
        dataset_id = self._authorized_dataset(str(manifest["dataset"]["source_sha256"]))
        metrics = manifest.get("metrics") or {}
        required = (
            "baseline_validation_loss",
            "validation_loss",
            "forgetting_regression",
            "ood_loss",
        )
        if any(metrics.get(field) is None for field in required):
            raise ValueError("ood_or_forgetting_metrics_missing")
        if float(metrics["forgetting_regression"]) > 0:
            raise ValueError("catastrophic_forgetting_regression")
        # El manifiesto ya declaraba a qué modelo pertenece el adaptador y se
        # descartaba al inscribirlo. Sin ese dato, la gobernanza no podía impedir
        # activar un adaptador de 0.5B sobre el modelo de 3B que sirve el
        # runtime, ni sobre otra familia entera.
        base_model = str(manifest.get("base_model") or "").strip()
        if not base_model:
            raise ValueError("adapter_base_model_missing")
        baseline_quality = -float(metrics["baseline_validation_loss"])
        version_id = f"peft-{uuid.uuid4().hex}"
        now = _now()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO governed_peft_versions
                (version_id, adapter_path, integrity_sha256, dataset_id, status,
                 traffic_percent, baseline_quality, rollback_ref, approved_by,
                 previous_version_id, created_at, updated_at, base_model)
                VALUES (?, ?, ?, ?, 'canary', ?, ?, ?, NULL, NULL, ?, ?, ?)""",
                (
                    version_id,
                    str(root),
                    bundle["bundle_sha256"],
                    dataset_id,
                    traffic_percent,
                    baseline_quality,
                    f"peft:{version_id}:restore_previous",
                    now,
                    now,
                    base_model,
                ),
            )
        return {
            "version_id": version_id,
            "status": "canary",
            "dataset_id": dataset_id,
            "traffic_percent": traffic_percent,
            "base_model": base_model,
        }

    def observe(
        self,
        version_id: str,
        *,
        quality: float,
        latency_ms: float,
        success: bool,
        evidence_ref: str,
    ) -> dict[str, Any]:
        if not evidence_ref:
            raise ValueError("canary_evidence_required")
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT baseline_quality,status FROM governed_peft_versions WHERE version_id=?",
                (version_id,),
            ).fetchone()
            if not row or row[1] != "canary":
                raise ValueError("version_not_in_canary")
            failed = not success or quality < float(row[0])
            conn.execute(
                "INSERT INTO governed_peft_observations VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    f"po-{uuid.uuid4().hex}",
                    version_id,
                    quality,
                    latency_ms,
                    int(success),
                    evidence_ref,
                    _now(),
                ),
            )
            if failed:
                conn.execute(
                    "UPDATE governed_peft_versions SET status='canary_failed',updated_at=? WHERE version_id=?",
                    (_now(), version_id),
                )
        return {
            "version_id": version_id,
            "status": "canary_failed" if failed else "canary",
        }

    def activate(self, version_id: str, *, approved_by: str) -> dict[str, Any]:
        if not approved_by.strip():
            return {"status": "blocked", "reason": "named_human_approval_required"}
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT status, base_model FROM governed_peft_versions WHERE version_id=?",
                (version_id,),
            ).fetchone()
            observations = conn.execute(
                "SELECT COUNT(*) FROM governed_peft_observations WHERE version_id=? AND success=1",
                (version_id,),
            ).fetchone()[0]
            if not row or row[0] != "canary" or observations < 1:
                return {"status": "blocked", "reason": "passing_canary_required"}
            # Un adaptador entrenado sobre un modelo que el runtime no sirve no
            # puede aplicarse a nada. Activarlo dejaría el slot de producción
            # apuntando a algo inservible, y con firma humana encima.
            base_model = str(row[1] or "")
            compatible = self._served_matching(base_model)
            if not compatible:
                return {
                    "status": "blocked",
                    "reason": "base_model_not_served",
                    "base_model": base_model or "UNKNOWN",
                    "served_models": self._resolve_served_models(),
                }
            current = conn.execute(
                "SELECT version_id FROM governed_peft_active_slot WHERE slot='production'"
            ).fetchone()
            previous = current[0] if current else None
            now = _now()
            conn.execute(
                "UPDATE governed_peft_versions SET status='active',approved_by=?,previous_version_id=?,updated_at=? WHERE version_id=?",
                (approved_by, previous, now, version_id),
            )
            conn.execute(
                """INSERT INTO governed_peft_active_slot VALUES ('production',?,?,?)
                ON CONFLICT(slot) DO UPDATE SET previous_version_id=governed_peft_active_slot.version_id,
                version_id=excluded.version_id,updated_at=excluded.updated_at""",
                (version_id, previous, now),
            )
        return {
            "status": "active",
            "version_id": version_id,
            "previous_version_id": previous,
        }

    def rollback(self, *, approved_by: str) -> dict[str, Any]:
        if not approved_by.strip():
            return {"status": "blocked", "reason": "named_human_approval_required"}
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT version_id,previous_version_id FROM governed_peft_active_slot WHERE slot='production'"
            ).fetchone()
            if not row:
                return {"status": "blocked", "reason": "no_active_version"}
            conn.execute(
                "UPDATE governed_peft_versions SET status='rolled_back',updated_at=? WHERE version_id=?",
                (_now(), row[0]),
            )
            conn.execute(
                "UPDATE governed_peft_active_slot SET version_id=?,previous_version_id=NULL,updated_at=? WHERE slot='production'",
                (row[1], _now()),
            )
        return {
            "status": "rolled_back",
            "removed_version_id": row[0],
            "version_id": row[1],
        }

    def status(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT version_id,previous_version_id,updated_at FROM governed_peft_active_slot WHERE slot='production'"
            ).fetchone()
        return (
            {"status": "base_only"}
            if not row or not row[0]
            else {
                "status": "active",
                "version_id": row[0],
                "previous_version_id": row[1],
                "updated_at": row[2],
            }
        )

    def _resolve_served_models(self) -> list[str]:
        """Modelos servidos: los inyectados, o los que Ollama declare ahora.

        Se pregunta en el momento de activar y no al construir: entre una cosa y
        otra pueden pasar días, y lo que importa es qué hay servido cuando el
        adaptador iría a producción. Si Ollama no responde, la lista queda vacía
        y `activate()` bloquea — sin evidencia no se activa.
        """
        if self.served_models is not None:
            return list(self.served_models)
        try:
            from triade.models.ollama_client import OllamaClient

            salud = OllamaClient().health()
            return [str(m) for m in (salud.get("models") or [])]
        except (OSError, ImportError, RuntimeError, ValueError, TypeError, KeyError):
            return []

    def _served_matching(self, base_model: str) -> list[str]:
        clave = normalize_model_id(base_model)
        if not clave:
            return []
        return [
            servido
            for servido in self._resolve_served_models()
            if normalize_model_id(servido) == clave
        ]

    def _verify_blobs(
        self, adapter_path: str | Path
    ) -> tuple[Path, dict[str, Any], dict[str, Any]]:
        root = Path(adapter_path).resolve()
        if self.adapters_root not in root.parents:
            raise ValueError("adapter_outside_governed_root")
        manifest = json.loads(
            (root / "triade_adapter_manifest.json").read_text(encoding="utf-8")
        )
        bundle = json.loads(
            (root / "serving_integrity.json").read_text(encoding="utf-8")
        )
        observed = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.iterdir())
            if path.is_file() and path.name != "serving_integrity.json"
        }
        if observed != bundle.get("files"):
            raise ValueError("adapter_blob_hash_mismatch")
        digest = hashlib.sha256(
            json.dumps(observed, sort_keys=True).encode()
        ).hexdigest()
        if digest != bundle.get("bundle_sha256"):
            raise ValueError("adapter_integrity_bundle_mismatch")
        return root, manifest, bundle

    def _authorized_dataset(self, source_sha256: str) -> str:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT dataset_id,status,governance_rules FROM governed_datasets"
            ).fetchall()
        for dataset_id, status, raw_rules in rows:
            rules = json.loads(raw_rules or "{}")
            if (
                status == "training_ready"
                and rules.get("source_sha256") == source_sha256
                and "lora_training" in rules.get("allowed_uses", [])
            ):
                return str(dataset_id)
        raise ValueError("dataset_not_authorized_for_lora_serving")

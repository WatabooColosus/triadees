"""Puerta de scheduler para LoRA: dataset gobernado, presupuesto y no activación."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from triade.core.governed_datasets import GovernedDatasets
from triade.db import sqlite3

from .lora_trainer import LoraTrainingConfig, RealLoraTrainer
from .serving_governance import (
    GovernedPeftServing,
    build_integrity_bundle,
    normalize_model_id,
)

#: Traducción de etiqueta Ollama a identificador HuggingFace.
#:
#: No es cosmética: `RealLoraTrainer` carga pesos de HuggingFace y el runtime
#: sirve etiquetas de Ollama. Sin el puente, la base por defecto era
#: `Qwen/Qwen2.5-0.5B-Instruct` —un modelo de 0,5B que **no está servido**—
#: mientras producción sirve `qwen2.5:3b-instruct`.
#:
#: Medido el 2026-08-27 con `normalize_model_id`: la clave de la base por
#: defecto era `qwen2.50.5binstruct` y ninguno de los cinco modelos servidos
#: reducía a eso. Cualquier adaptador entrenado con la configuración de fábrica
#: era **inactivable por construcción**: `activate()` bloquea por
#: incompatibilidad, correctamente, y el trabajo de entrenamiento se tiraba
#: entero. `goal_lora_train` y `governed_peft_active_slot` estaban muertos por
#: la misma razón que lo estuvo el circuito de automejora: no podían empezar.
_OLLAMA_A_HUGGINGFACE: dict[str, str] = {
    "qwen2.5:3b-instruct": "Qwen/Qwen2.5-3B-Instruct",
    "qwen2.5-coder:3b": "Qwen/Qwen2.5-Coder-3B",
    "qwen3:1.7b": "Qwen/Qwen3-1.7B",
    "qwen3:4b": "Qwen/Qwen3-4B",
    "gemma3:4b": "google/gemma-3-4b-it",
}


def default_base_model(config_path: str | Path = "triade.yml") -> str:
    """La base a entrenar, derivada del modelo que el runtime sirve de verdad.

    Se lee de `models.roles.central`, que es el modelo con el que responde el
    sistema. Entrenar contra otro produce un adaptador que la compuerta de
    servicio rechazará, y hacerlo por defecto convertía la capacidad entera en
    inalcanzable.
    """
    from triade.core.config import load_config

    try:
        cfg = load_config(config_path)
    except (OSError, ValueError, TypeError, KeyError):
        cfg = {}
    roles = (
        ((cfg.get("models") or {}).get("roles") or {}) if isinstance(cfg, dict) else {}
    )
    etiqueta = str(roles.get("central") or "").strip()
    return _OLLAMA_A_HUGGINGFACE.get(etiqueta, "") or etiqueta


def served_model_labels(config_path: str | Path = "triade.yml") -> list[str]:
    """Etiquetas de los modelos que el runtime declara servir."""
    from triade.core.config import load_config

    try:
        cfg = load_config(config_path)
    except (OSError, ValueError, TypeError, KeyError):
        return []
    roles = (
        ((cfg.get("models") or {}).get("roles") or {}) if isinstance(cfg, dict) else {}
    )
    return [str(v).strip() for v in roles.values() if str(v).strip()]


class GovernedLoraJobRunner:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS lora_jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT, goal_id TEXT, dataset_path TEXT, base_model TEXT,
                max_steps INTEGER, status TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT, result_json TEXT, error TEXT)""")

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not payload.get("human_approved") or not payload.get("approved_by"):
            return {"status": "blocked", "reason": "explicit_human_approval_required"}
        dataset = Path(str(payload.get("dataset_path") or "")).resolve()
        allowed = [Path("data/lora").resolve(), Path("artifacts/datasets").resolve()]
        if not dataset.is_file() or not any(
            root == dataset.parent or root in dataset.parents for root in allowed
        ):
            return {"status": "blocked", "reason": "dataset_not_in_governed_storage"}
        max_steps = max(1, min(int(payload.get("max_steps") or 20), 100))
        goal_id = str(payload.get("goal_id") or "manual")
        output = Path("artifacts/adapters") / f"{goal_id}-{max_steps}steps"
        base_model = str(payload.get("base_model") or "") or default_base_model()
        if not base_model:
            return {"status": "blocked", "reason": "no_served_model_configured"}
        # Se comprueba **antes** de gastar GPU. Entrenar contra una base que la
        # compuerta de servicio va a rechazar es tirar el trabajo entero, y el
        # rechazo llegaba al final, tras el entrenamiento.
        clave = normalize_model_id(base_model)
        if not any(normalize_model_id(s) == clave for s in served_model_labels()):
            return {
                "status": "blocked",
                "reason": "base_model_not_served",
                "base_model": base_model,
                "served": served_model_labels(),
            }
        # Estas dos muestras son parte del contrato de entrada, no un detalle
        # opcional de evaluación. Sin OOD no se puede inscribir el adaptador y
        # sin una muestra de olvido independiente no hay evidencia causal de
        # que el ajuste haya preservado lo que el modelo ya sabía.
        ood = self._governed_auxiliary_path(payload.get("ood_path"))
        if ood is None:
            return {"status": "blocked", "reason": "ood_dataset_required"}
        forgetting = self._governed_auxiliary_path(payload.get("forgetting_path"))
        if forgetting is None:
            return {"status": "blocked", "reason": "forgetting_dataset_required"}
        dataset_authorization = GovernedDatasets(
            self.db_path
        ).authorize_training_source(dataset)
        if not dataset_authorization["allowed"]:
            return {
                "status": "blocked",
                "reason": dataset_authorization["reason"],
                "dataset_authorization": dataset_authorization,
            }
        config = LoraTrainingConfig(
            base_model=base_model,
            output_dir=str(output),
            max_steps=max_steps,
            maximum_gpu_minutes=min(
                float(payload.get("maximum_gpu_minutes") or 30), 120
            ),
        )
        with sqlite3.connect(self.db_path) as conn:
            job_id = conn.execute(
                "INSERT INTO lora_jobs(goal_id,dataset_path,base_model,max_steps,status) VALUES(?,?,?,?,?)",
                (goal_id, str(dataset), config.base_model, max_steps, "running"),
            ).lastrowid
        try:
            result = RealLoraTrainer(config).train(
                dataset,
                ood_path=ood,
                forgetting_path=forgetting,
                db_path=self.db_path,
            )
            adapter_path = Path(str(result.get("output_dir") or "")).resolve()
            adapters_root = Path("artifacts/adapters").resolve()
            if not adapter_path.is_dir() or adapters_root not in adapter_path.parents:
                raise ValueError("trainer_output_outside_governed_adapters")
            build_integrity_bundle(adapter_path)
            canary = GovernedPeftServing(
                self.db_path,
                adapters_root,
                served_models=served_model_labels(),
            ).enroll(adapter_path, traffic_percent=5.0)
            result.update(
                {
                    # Estado canónico del worker; el estado de negocio queda en
                    # `canary.status` y en `governed_peft_versions`.
                    "status": "completed",
                    "job_id": job_id,
                    "canary_required": True,
                    "canary": canary,
                    "dataset_authorization": dataset_authorization,
                    "automatic_activation": False,
                    "effect_receipt": {
                        "action": "enroll_peft_canary",
                        "target": canary["version_id"],
                        "precondition": {
                            "human_approved": True,
                            "base_model_served": True,
                            "dataset_authorized": True,
                            "dataset_id": dataset_authorization["dataset_id"],
                        },
                        "execution": {
                            "job_id": job_id,
                            "traffic_percent": canary["traffic_percent"],
                        },
                        "postcondition": {
                            "passed": canary["status"] == "canary",
                            "status": canary["status"],
                        },
                        "verified": canary["status"] == "canary",
                        "verifier": "governed_peft_serving_enroll",
                        "evidence_refs": [
                            str(adapter_path / "triade_adapter_manifest.json"),
                            str(adapter_path / "serving_integrity.json"),
                        ],
                        "rollback_ref": str(adapter_path / "rollback.json"),
                        "rollback_required": True,
                    },
                }
            )
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE lora_jobs SET status='canary',finished_at=CURRENT_TIMESTAMP,result_json=? WHERE id=?",
                    (json.dumps(result, default=str), job_id),
                )
            return result
        except (
            OSError,
            ImportError,
            sqlite3.Error,
            RuntimeError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ) as exc:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE lora_jobs SET status='failed',finished_at=CURRENT_TIMESTAMP,error=? WHERE id=?",
                    (str(exc), job_id),
                )
            return {
                "status": "error",
                "job_id": job_id,
                "error": str(exc),
                "automatic_activation": False,
            }

    @staticmethod
    def _governed_auxiliary_path(value: Any) -> Path | None:
        if not str(value or "").strip():
            return None
        candidate = Path(str(value)).resolve()
        roots = [Path("data/lora").resolve(), Path("artifacts/datasets").resolve()]
        if not candidate.is_file() or not any(
            root == candidate.parent or root in candidate.parents for root in roots
        ):
            return None
        return candidate

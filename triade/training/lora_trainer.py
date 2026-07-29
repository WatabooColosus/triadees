"""Entrenamiento LoRA real con PEFT, evaluación y artefactos reversibles."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import random
import re
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PII = re.compile(
    r"(?:\b\d{3}-\d{2}-\d{4}\b|\b(?:sk-|ghp_|AIza)[A-Za-z0-9_-]{12,}|password\s*[:=]|contrase(?:ña|na)\s*[:=])",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class LoraTrainingConfig:
    base_model: str = "Qwen/Qwen2.5-0.5B-Instruct"
    output_dir: str = "artifacts/adapters/triade-lora"
    rank: int = 8
    alpha: int = 16
    dropout: float = 0.05
    target_modules: tuple[str, ...] = ("q_proj", "k_proj", "v_proj", "o_proj")
    learning_rate: float = 1e-4
    batch_size: int = 1
    gradient_accumulation_steps: int = 4
    max_steps: int = 20
    max_length: int = 512
    seed: int = 42
    validation_fraction: float = 0.20
    maximum_examples: int = 2000
    maximum_gpu_minutes: float = 120.0
    minimum_examples: int = 5
    gradient_clip_norm: float = 1.0
    trust_remote_code: bool = False


class _Rows:
    def __init__(
        self, rows: list[dict[str, Any]], tokenizer: Any, max_length: int
    ) -> None:
        self.items = [self._encode(row, tokenizer, max_length) for row in rows]

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> dict[str, Any]:
        return self.items[index]

    @staticmethod
    def _encode(row: dict[str, Any], tokenizer: Any, max_length: int) -> dict[str, Any]:
        instruction = str(row["instruction"]).strip()
        context = str(row.get("context") or "").strip()
        response = str(row["response"]).strip()
        prompt = f"Instrucción: {instruction}\n"
        if context:
            prompt += f"Contexto: {context}\n"
        prompt += "Respuesta:"
        full = prompt + " " + response + (tokenizer.eos_token or "")
        encoded = tokenizer(
            full, truncation=True, max_length=max_length, add_special_tokens=True
        )
        prompt_ids = tokenizer(
            prompt, truncation=True, max_length=max_length, add_special_tokens=True
        )["input_ids"]
        labels = list(encoded["input_ids"])
        mask_to = min(len(prompt_ids), len(labels) - 1)
        labels[:mask_to] = [-100] * mask_to
        return {
            "input_ids": encoded["input_ids"],
            "attention_mask": encoded["attention_mask"],
            "labels": labels,
        }


class RealLoraTrainer:
    def __init__(self, config: LoraTrainingConfig | None = None) -> None:
        self.config = config or LoraTrainingConfig()

    def prepare_dataset(self, dataset_path: str | Path) -> dict[str, Any]:
        rows = self._read_rows(dataset_path)
        if len(rows) < self.config.minimum_examples:
            raise ValueError(
                f"se requieren al menos {self.config.minimum_examples} ejemplos gobernados"
            )
        unique: dict[str, dict[str, Any]] = {}
        rejected_pii = 0
        for row in rows[: self.config.maximum_examples]:
            text = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if PII.search(text):
                rejected_pii += 1
                continue
            digest = hashlib.sha256(text.encode()).hexdigest()
            unique[digest] = row
        if len(unique) < self.config.minimum_examples:
            raise ValueError(
                f"quedan {len(unique)} ejemplos válidos; se requieren al menos {self.config.minimum_examples} tras filtrar y deduplicar"
            )
        material = sorted(unique.items())
        rng = random.Random(self.config.seed)
        rng.shuffle(material)
        split = max(1, round(len(material) * self.config.validation_fraction))
        validation = [row for _, row in material[:split]]
        train = [row for _, row in material[split:]]
        if not train:
            raise ValueError("el split dejó entrenamiento vacío")
        manifest = {
            "source_sha256": hashlib.sha256(
                Path(dataset_path).read_bytes()
            ).hexdigest(),
            "total_read": len(rows),
            "deduplicated": len(unique),
            "rejected_pii": rejected_pii,
            "train_count": len(train),
            "validation_count": len(validation),
            "seed": self.config.seed,
            "train_hash": self._rows_hash(train),
            "validation_hash": self._rows_hash(validation),
        }
        return {"train": train, "validation": validation, "manifest": manifest}

    def train(
        self,
        dataset_path: str | Path,
        *,
        ood_path: str | Path | None = None,
        forgetting_path: str | Path | None = None,
        campaign_id: str | None = None,
        db_path: str | Path = "triade/memory/triade.db",
    ) -> dict[str, Any]:
        import torch
        from peft import LoraConfig, get_peft_model
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if not torch.cuda.is_available():
            raise RuntimeError("LoRA real requiere CUDA en esta configuración")
        prepared = self.prepare_dataset(dataset_path)
        output = Path(self.config.output_dir).resolve()
        output.mkdir(parents=True, exist_ok=True)
        tokenizer = AutoTokenizer.from_pretrained(
            self.config.base_model, trust_remote_code=self.config.trust_remote_code
        )
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        model = AutoModelForCausalLM.from_pretrained(
            self.config.base_model,
            dtype=torch.bfloat16,
            trust_remote_code=self.config.trust_remote_code,
        ).to("cuda")
        model.config.use_cache = False
        lora = LoraConfig(
            r=self.config.rank,
            lora_alpha=self.config.alpha,
            lora_dropout=self.config.dropout,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=list(self.config.target_modules),
        )
        model = get_peft_model(model, lora)
        trainable, total = model.get_nb_trainable_parameters()
        train_ds = _Rows(prepared["train"], tokenizer, self.config.max_length)
        val_ds = _Rows(prepared["validation"], tokenizer, self.config.max_length)
        forgetting_rows = (
            self._read_rows(forgetting_path)
            if forgetting_path
            else prepared["validation"]
        )
        forgetting_ds = _Rows(forgetting_rows, tokenizer, self.config.max_length)
        baseline_val = self._evaluate_loss(model, val_ds, tokenizer.pad_token_id)
        baseline_forgetting = self._evaluate_loss(
            model, forgetting_ds, tokenizer.pad_token_id
        )
        optimizer = torch.optim.AdamW(
            (p for p in model.parameters() if p.requires_grad),
            lr=self.config.learning_rate,
        )
        torch.manual_seed(self.config.seed)
        random.seed(self.config.seed)
        start = time.monotonic()
        losses: list[float] = []
        step = 0
        optimizer.zero_grad(set_to_none=True)
        model.train()
        while step < self.config.max_steps:
            for index in range(len(train_ds)):
                batch = self._collate([train_ds[index]], tokenizer.pad_token_id, torch)
                batch = {k: v.to("cuda") for k, v in batch.items()}
                loss = model(**batch).loss / self.config.gradient_accumulation_steps
                loss.backward()
                losses.append(
                    float(loss.detach().cpu()) * self.config.gradient_accumulation_steps
                )
                if (len(losses) % self.config.gradient_accumulation_steps) == 0:
                    torch.nn.utils.clip_grad_norm_(
                        model.parameters(), self.config.gradient_clip_norm
                    )
                    optimizer.step()
                    optimizer.zero_grad(set_to_none=True)
                    step += 1
                    if step >= self.config.max_steps:
                        break
                if (time.monotonic() - start) / 60 > self.config.maximum_gpu_minutes:
                    raise TimeoutError("presupuesto GPU excedido")
            if not len(train_ds):
                break
        if any(p.grad is not None for p in model.parameters() if p.requires_grad):
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
        post_val = self._evaluate_loss(model, val_ds, tokenizer.pad_token_id)
        post_forgetting = self._evaluate_loss(
            model, forgetting_ds, tokenizer.pad_token_id
        )
        ood_loss = None
        if ood_path:
            ood_loss = self._evaluate_loss(
                model,
                _Rows(self._read_rows(ood_path), tokenizer, self.config.max_length),
                tokenizer.pad_token_id,
            )
        model.save_pretrained(output, safe_serialization=True)
        tokenizer.save_pretrained(output)
        adapter_file = output / "adapter_model.safetensors"
        if not adapter_file.is_file():
            raise RuntimeError("PEFT no produjo adapter_model.safetensors")
        adapter_sha = hashlib.sha256(adapter_file.read_bytes()).hexdigest()
        elapsed = time.monotonic() - start
        metrics = {
            "baseline_validation_loss": baseline_val,
            "validation_loss": post_val,
            "validation_improvement": baseline_val - post_val,
            "baseline_forgetting_loss": baseline_forgetting,
            "forgetting_loss": post_forgetting,
            "forgetting_regression": post_forgetting - baseline_forgetting,
            "ood_loss": ood_loss,
            "training_loss": sum(losses) / max(len(losses), 1),
            "steps": step,
            "elapsed_seconds": round(elapsed, 3),
            "gpu_minutes": round(elapsed / 60, 4),
            "trainable_parameters": trainable,
            "total_parameters": total,
            "trainable_percent": round(100 * trainable / total, 6),
        }
        manifest = {
            "format": "peft-lora",
            "base_model": self.config.base_model,
            "adapter_sha256": adapter_sha,
            "config": asdict(self.config),
            "dataset": prepared["manifest"],
            "metrics": metrics,
            "rollback": {
                "action": "unload_adapter",
                "base_model": self.config.base_model,
                "automatic_activation": False,
            },
        }
        manifest["manifest_sha256"] = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, default=str).encode()
        ).hexdigest()
        key = os.getenv("TRIADE_ADAPTER_SIGNING_KEY", "").encode()
        manifest["signature"] = (
            hmac.new(
                key, manifest["manifest_sha256"].encode(), hashlib.sha256
            ).hexdigest()
            if key
            else None
        )
        (output / "triade_adapter_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        (output / "rollback.json").write_text(
            json.dumps(manifest["rollback"], indent=2), encoding="utf-8"
        )
        if campaign_id:
            self._record_evolution(
                campaign_id, db_path, output, prepared["manifest"], metrics
            )
        del model
        torch.cuda.empty_cache()
        return {
            "status": "trained_not_activated",
            "output_dir": str(output),
            "adapter_sha256": adapter_sha,
            "manifest_sha256": manifest["manifest_sha256"],
            "dataset": prepared["manifest"],
            "metrics": metrics,
            "rollback_ready": True,
            "automatic_activation": False,
        }

    @staticmethod
    def _read_rows(path: str | Path | None) -> list[dict[str, Any]]:
        if path is None:
            return []
        rows = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if (
                not str(row.get("instruction", "")).strip()
                or not str(row.get("response", "")).strip()
            ):
                raise ValueError("cada ejemplo requiere instruction y response")
            rows.append(row)
        return rows

    @staticmethod
    def _rows_hash(rows: Iterable[dict[str, Any]]) -> str:
        return hashlib.sha256(
            json.dumps(list(rows), ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()

    @staticmethod
    def _collate(
        items: list[dict[str, Any]], pad_token_id: int, torch: Any
    ) -> dict[str, Any]:
        length = max(len(item["input_ids"]) for item in items)

        def pad(values: list[int], fill: int) -> list[int]:
            return values + [fill] * (length - len(values))

        return {
            "input_ids": torch.tensor(
                [pad(x["input_ids"], pad_token_id) for x in items], dtype=torch.long
            ),
            "attention_mask": torch.tensor(
                [pad(x["attention_mask"], 0) for x in items], dtype=torch.long
            ),
            "labels": torch.tensor(
                [pad(x["labels"], -100) for x in items], dtype=torch.long
            ),
        }

    def _evaluate_loss(self, model: Any, dataset: _Rows, pad_token_id: int) -> float:
        import torch

        if not len(dataset):
            return math.inf
        model.eval()
        losses = []
        with torch.no_grad():
            for index in range(len(dataset)):
                batch = self._collate([dataset[index]], pad_token_id, torch)
                batch = {k: v.to("cuda") for k, v in batch.items()}
                losses.append(float(model(**batch).loss.detach().cpu()))
        model.train()
        return round(sum(losses) / len(losses), 6)

    @staticmethod
    def _record_evolution(
        campaign_id: str,
        db_path: str | Path,
        output: Path,
        dataset_manifest: dict[str, Any],
        metrics: dict[str, Any],
    ) -> None:
        from triade.evolution import EvolutionLab, Stage

        lab = EvolutionLab(db_path)
        lab.record_evidence(
            campaign_id,
            Stage.ADAPTER,
            "dataset_split",
            dataset_manifest,
            source="real-lora-trainer",
        )
        lab.record_evidence(
            campaign_id,
            Stage.ADAPTER,
            "adapter_training",
            metrics,
            source="real-lora-trainer",
        )
        lab.record_evidence(
            campaign_id,
            Stage.ADAPTER,
            "ood_evaluation",
            {"loss": metrics.get("ood_loss")},
            source="real-lora-trainer",
            independent=True,
        )
        lab.record_evidence(
            campaign_id,
            Stage.ADAPTER,
            "forgetting_evaluation",
            {"regression": metrics.get("forgetting_regression")},
            source="real-lora-trainer",
            independent=True,
        )
        lab.register_artifact(
            campaign_id,
            "adapter",
            output / "adapter_model.safetensors",
            metadata=metrics,
        )

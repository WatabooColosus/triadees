"""Serving PEFT canary gobernado, lazy-load, activación y rollback."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

from triade.db import sqlite3


class PeftCanaryServer:
    _lock = threading.RLock()
    _model: Any = None
    _tokenizer: Any = None
    _loaded_adapter: str | None = None

    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        adapters_root: str | Path = "artifacts/adapters",
    ) -> None:
        self.db_path, self.adapters_root = Path(db_path), Path(adapters_root).resolve()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS peft_canary_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT, adapter_path TEXT, event TEXT, approved_by TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, success INTEGER, latency_ms REAL,
                prompt_sha256 TEXT, result_json TEXT, error TEXT)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS peft_serving_state(
                slot TEXT PRIMARY KEY, adapter_path TEXT, status TEXT, activated_at TEXT,
                approved_by TEXT, previous_adapter_path TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

    def _resolve(self, adapter_path: str) -> Path:
        path = Path(adapter_path).resolve()
        if (
            self.adapters_root not in path.parents
            or not (path / "adapter_model.safetensors").is_file()
        ):
            raise ValueError("adaptador fuera del registro local o incompleto")
        manifest_path = path / "triade_adapter_manifest.json"
        if not manifest_path.is_file():
            raise ValueError("manifiesto de adaptador ausente")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        actual = hashlib.sha256(
            (path / "adapter_model.safetensors").read_bytes()
        ).hexdigest()
        if actual != manifest.get("adapter_sha256"):
            raise ValueError("hash del adaptador no coincide con el manifiesto")
        return path

    def _load(self, adapter_path: str) -> tuple[Any, Any, Path]:
        path = self._resolve(adapter_path)
        with self._lock:
            if self._loaded_adapter == str(path) and self._model is not None:
                return self._model, self._tokenizer, path
            import torch
            from peft import PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer

            manifest = json.loads(
                (path / "triade_adapter_manifest.json").read_text(encoding="utf-8")
            )
            base_model = str(manifest["base_model"])
            tokenizer = AutoTokenizer.from_pretrained(path)
            base = AutoModelForCausalLM.from_pretrained(
                base_model,
                dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                trust_remote_code=False,
            )
            model = PeftModel.from_pretrained(base, path, is_trainable=False)
            model = model.to("cuda" if torch.cuda.is_available() else "cpu").eval()
            self._model, self._tokenizer, self._loaded_adapter = (
                model,
                tokenizer,
                str(path),
            )
            return model, tokenizer, path

    def generate(
        self, adapter_path: str, prompt: str, *, max_new_tokens: int = 64
    ) -> dict[str, Any]:
        if not prompt.strip():
            return {"status": "blocked", "reason": "empty_prompt"}
        started = time.monotonic()
        digest = hashlib.sha256(prompt.encode()).hexdigest()
        try:
            import torch

            model, tokenizer, path = self._load(adapter_path)
            encoded = tokenizer(
                prompt, return_tensors="pt", truncation=True, max_length=1024
            )
            encoded = {key: value.to(model.device) for key, value in encoded.items()}
            with torch.inference_mode():
                output = model.generate(
                    **encoded,
                    max_new_tokens=max(1, min(max_new_tokens, 256)),
                    do_sample=False,
                )
            text = tokenizer.decode(
                output[0][encoded["input_ids"].shape[1] :], skip_special_tokens=True
            )
            latency = round((time.monotonic() - started) * 1000, 2)
            result = {
                "status": "completed",
                "adapter_path": str(path),
                "response": text,
                "latency_ms": latency,
                "canary": True,
                "production_share": 0.0,
            }
            self._event(
                str(path), "canary_generation", True, latency, digest, result=result
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
            self._event(
                adapter_path, "canary_generation", False, 0, digest, error=str(exc)
            )
            return {"status": "error", "error": str(exc), "canary": True}

    def activate(self, adapter_path: str, *, approved_by: str) -> dict[str, Any]:
        if not approved_by:
            return {"status": "blocked", "reason": "named_human_approval_required"}
        path = self._resolve(adapter_path)
        with sqlite3.connect(self.db_path) as conn:
            passed = conn.execute(
                "SELECT COUNT(*) FROM peft_canary_events WHERE adapter_path=? AND event='canary_generation' AND success=1",
                (str(path),),
            ).fetchone()[0]
            if not passed:
                return {"status": "blocked", "reason": "successful_canary_required"}
            current = conn.execute(
                "SELECT adapter_path FROM peft_serving_state WHERE slot='production'"
            ).fetchone()
            previous = current[0] if current else None
            conn.execute(
                """INSERT INTO peft_serving_state(slot,adapter_path,status,activated_at,approved_by,previous_adapter_path)
                VALUES('production',?,'active',CURRENT_TIMESTAMP,?,?) ON CONFLICT(slot) DO UPDATE SET
                previous_adapter_path=peft_serving_state.adapter_path,adapter_path=excluded.adapter_path,status='active',
                activated_at=CURRENT_TIMESTAMP,approved_by=excluded.approved_by,updated_at=CURRENT_TIMESTAMP""",
                (str(path), approved_by, previous),
            )
        self._event(str(path), "activated", True, 0, None, approved_by=approved_by)
        return {
            "status": "active",
            "adapter_path": str(path),
            "previous_adapter_path": previous,
            "approved_by": approved_by,
            "rollback_ready": True,
        }

    def rollback(self, *, approved_by: str) -> dict[str, Any]:
        if not approved_by:
            return {"status": "blocked", "reason": "named_human_approval_required"}
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT adapter_path,previous_adapter_path FROM peft_serving_state WHERE slot='production'"
            ).fetchone()
            if not row:
                return {"status": "blocked", "reason": "no_active_adapter"}
            conn.execute(
                "UPDATE peft_serving_state SET adapter_path=?,previous_adapter_path=?,status=?,approved_by=?,updated_at=CURRENT_TIMESTAMP WHERE slot='production'",
                (row[1], row[0], "active" if row[1] else "base_only", approved_by),
            )
        self.unload()
        return {
            "status": "rolled_back",
            "adapter_path": row[1],
            "removed_adapter": row[0],
        }

    @classmethod
    def unload(cls) -> None:
        with cls._lock:
            cls._model = cls._tokenizer = cls._loaded_adapter = None
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

    def status(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM peft_serving_state WHERE slot='production'"
            ).fetchone()
            recent = [
                dict(item)
                for item in conn.execute(
                    "SELECT * FROM peft_canary_events ORDER BY id DESC LIMIT 20"
                )
            ]
        active_in_db = bool(row and str(row["status"]) == "active")
        return {
            "status": "ok",
            "serving": dict(row) if row else {"status": "base_only"},
            "loaded_in_process": self._loaded_adapter,
            "recent_events": recent,
            # Verdad de servicio (auditoría 2026-07-31, P0-01). `peft_serving_state`
            # podía decir slot=production/status=active mientras NINGÚN componente
            # de la ruta de inferencia leía ese slot: las respuestas salen por HTTP
            # a Ollama, que no recibe adaptador. Se expone explícitamente para que
            # ningún panel ni decisión interprete "active" como "está sirviendo".
            "served_by_inference": False,
            "serving_truth": {
                "adapter_approved_and_registered": active_in_db,
                "loaded_in_this_process": self._loaded_adapter is not None,
                "used_by_production_inference": False,
                "effective_state": "approved_not_served"
                if active_in_db
                else "base_only",
                "reason": (
                    "La inferencia de producción usa Ollama (proceso externo) y no "
                    "consulta peft_serving_state. Un adaptador marcado 'active' aquí "
                    "no influye en ninguna respuesta real. Para servirlo haría falta "
                    "fusionarlo como modelo Ollama o mover la inferencia al motor PEFT."
                ),
            },
        }

    def pending_approval(self) -> dict[str, Any]:
        """Adaptadores con al menos un canary exitoso que aún no están en
        producción — listos para una aprobación humana rápida, de un clic.

        No decide nada por sí solo: activate() sigue exigiendo approved_by
        no vacío. Esto solo hace visible lo que ya pasó la barra automática
        para que un humano no tenga que ir a buscarlo.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            passed = conn.execute(
                """SELECT adapter_path, COUNT(*) AS successful_canaries,
                          MAX(created_at) AS last_success_at
                   FROM peft_canary_events
                   WHERE event = 'canary_generation' AND success = 1
                   GROUP BY adapter_path"""
            ).fetchall()
            current = conn.execute(
                "SELECT adapter_path FROM peft_serving_state "
                "WHERE slot = 'production' AND status = 'active'"
            ).fetchone()
        active_path = current["adapter_path"] if current else None
        pending = [
            {
                "adapter_path": row["adapter_path"],
                "successful_canaries": row["successful_canaries"],
                "last_success_at": row["last_success_at"],
            }
            for row in passed
            if row["adapter_path"] != active_path
        ]
        return {
            "status": "ok",
            "active_adapter_path": active_path,
            "pending_count": len(pending),
            "pending": pending,
        }

    def _event(
        self,
        path: str,
        event: str,
        success: bool,
        latency: float,
        prompt_sha: str | None,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        approved_by: str | None = None,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO peft_canary_events(adapter_path,event,approved_by,success,latency_ms,prompt_sha256,result_json,error) VALUES(?,?,?,?,?,?,?,?)",
                (
                    path,
                    event,
                    approved_by,
                    int(success),
                    latency,
                    prompt_sha,
                    json.dumps(result or {}),
                    error,
                ),
            )

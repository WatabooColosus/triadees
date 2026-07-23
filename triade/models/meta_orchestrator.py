"""Meta-Model Orchestrator · discovers, evaluates, and adopts Ollama models.

Maintains a curated catalog, benchmarks candidates against current models,
and automatically adopts or rejects based on improvement thresholds.
Persists all decisions in SQLite for auditability.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ModelCandidate:
    name: str
    size_bytes: int = 0
    parameter_count: str = ""
    description: str = ""
    source_url: str = ""
    compatible: bool = True
    estimated_vram_gb: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ModelEvaluation:
    model_name: str
    task_type: str
    score: float = 0.0
    latency_ms: int = 0
    quality_notes: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ModelDecision:
    model_name: str
    decision: str = "monitor"
    reason: str = ""
    previous_model: str = ""
    improvement_pct: float = 0.0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# SQL schemas
# ---------------------------------------------------------------------------

_CANDIDATES_TABLE = """
CREATE TABLE IF NOT EXISTS meta_model_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL UNIQUE,
    size_bytes INTEGER DEFAULT 0,
    parameter_count TEXT DEFAULT '',
    description TEXT DEFAULT '',
    source_url TEXT DEFAULT '',
    compatible INTEGER DEFAULT 1,
    estimated_vram_gb REAL DEFAULT 0.0,
    status TEXT DEFAULT 'discovered',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

_EVALUATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS meta_model_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    task_type TEXT NOT NULL,
    score REAL DEFAULT 0.0,
    latency_ms INTEGER DEFAULT 0,
    quality_notes TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

_DECISIONS_TABLE = """
CREATE TABLE IF NOT EXISTS meta_model_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT DEFAULT '',
    previous_model TEXT DEFAULT '',
    improvement_pct REAL DEFAULT 0.0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


# ---------------------------------------------------------------------------
# Curated catalog
# ---------------------------------------------------------------------------

MODEL_CATALOG: list[dict[str, Any]] = [
    {"name": "qwen2.5:3b", "size_bytes": 2 * 1024**3, "parameter_count": "3B", "description": "Fast, lightweight general model."},
    {"name": "qwen2.5:7b", "size_bytes": round(4.7 * 1024**3), "parameter_count": "7B", "description": "Balanced performance and speed."},
    {"name": "qwen2.5:14b", "size_bytes": round(9 * 1024**3), "parameter_count": "14B", "description": "High quality reasoning."},
    {"name": "qwen2.5:30b", "size_bytes": round(19 * 1024**3), "parameter_count": "30B", "description": "Advanced reasoning, requires significant VRAM."},
    {"name": "qwen2.5:70b", "size_bytes": round(40 * 1024**3), "parameter_count": "70B", "description": "Top-tier reasoning, needs high-end GPU cluster."},
    {"name": "codellama:7b", "size_bytes": round(3.8 * 1024**3), "parameter_count": "7B", "description": "Code generation specialist."},
    {"name": "codellama:13b", "size_bytes": round(7.4 * 1024**3), "parameter_count": "13B", "description": "Advanced code generation."},
    {"name": "gemma2:9b", "size_bytes": round(5.4 * 1024**3), "parameter_count": "9B", "description": "Google's high-quality model."},
    {"name": "llama3:8b", "size_bytes": round(4.7 * 1024**3), "parameter_count": "8B", "description": "Meta's versatile general model."},
]

DEFAULT_BENCHMARK_PROMPTS: dict[str, str] = {
    "reasoning": "Resolve: si todos los bloques rojos pesan 2kg y los azules 3kg, ¿cuánto pesan 4 rojos y 3 azules? Explica paso a paso.",
    "coding": "Escribe una función en Python que determine si un número es primo, con manejo de edge cases.",
    "summarization": "Resume en 2 oraciones: La inteligencia artificial ha transformado múltiples industrias desde 2020, desde la atención médica hasta la educación, generando tanto optimismo como preocupaciones éticas sobre sesgo y privacidad.",
    "translation": "Traduce al inglés: 'El conocimiento es el único recurso que se multiplica cuando se comparte.'",
    "general": "¿Cuáles son las tres leyes de la robótica de Asimov y por qué son relevantes hoy?",
}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class MetaModelOrchestrator:
    """Discovers, evaluates, and adopts Ollama models automatically."""

    ADOPT_THRESHOLD_PCT = 15.0
    ADOPT_SMALL_THRESHOLD_PCT = 5.0
    SMALL_MODEL_MAX_BYTES = round(5 * 1024**3)
    OLLAMA_BASE_URL = "http://127.0.0.1:11434"
    VRAM_OVERHEAD_GB = 1.5

    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        hardware_profile: Any | None = None,
        model_client: Any | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.hardware = hardware_profile
        self.model_client = model_client
        self._ensure_tables()

    # ---- DB helpers -------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        with self._connect() as conn:
            conn.execute(_CANDIDATES_TABLE)
            conn.execute(_EVALUATIONS_TABLE)
            conn.execute(_DECISIONS_TABLE)

    # ---- Discovery --------------------------------------------------------

    def discover_models(self) -> list[ModelCandidate]:
        installed = self._get_installed_models()
        catalog = self._build_catalog(installed)
        self._persist_candidates(catalog)
        return catalog

    def _get_installed_models(self) -> dict[str, dict[str, Any]]:
        request = urllib.request.Request(
            f"{self.OLLAMA_BASE_URL}/api/tags",
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                body = json.loads(response.read().decode("utf-8"))
                models: dict[str, dict[str, Any]] = {}
                for entry in body.get("models", []):
                    name = str(entry.get("name", ""))
                    size = int(entry.get("size", 0))
                    details = self._fetch_model_details(name)
                    models[name] = {"name": name, "size": size, "details": details}
                return models
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return {}

    def _fetch_model_details(self, model_name: str) -> dict[str, Any]:
        data = json.dumps({"name": model_name}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.OLLAMA_BASE_URL}/api/show",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return {}

    def _build_catalog(self, installed: dict[str, dict[str, Any]]) -> list[ModelCandidate]:
        candidates: list[ModelCandidate] = []
        max_vram = self._get_available_vram()

        for entry in MODEL_CATALOG:
            name = entry["name"]
            size_bytes = int(entry.get("size_bytes", 0))
            est_vram = round(size_bytes / 1024**3 + self.VRAM_OVERHEAD_GB, 2)
            compatible = est_vram <= max_vram if max_vram > 0 else False

            if name in installed:
                compatible = True

            candidates.append(ModelCandidate(
                name=name,
                size_bytes=size_bytes,
                parameter_count=str(entry.get("parameter_count", "")),
                description=str(entry.get("description", "")),
                source_url=f"https://ollama.com/library/{name.split(':')[0]}",
                compatible=compatible,
                estimated_vram_gb=est_vram,
            ))

        for inst_name, inst_data in installed.items():
            if inst_name not in {c.name for c in candidates}:
                size_bytes = int(inst_data.get("size", 0))
                candidates.append(ModelCandidate(
                    name=inst_name,
                    size_bytes=size_bytes,
                    parameter_count="",
                    description="Currently installed.",
                    compatible=True,
                    estimated_vram_gb=round(size_bytes / 1024**3 + self.VRAM_OVERHEAD_GB, 2),
                ))

        return candidates

    def _get_available_vram(self) -> float:
        if self.hardware and hasattr(self.hardware, "gpus"):
            vrams = [gpu.vram_total_gb for gpu in self.hardware.gpus if gpu.vram_total_gb > 0]
            if vrams:
                return max(vrams)
        if self.hardware and hasattr(self.hardware, "ram_available_gb"):
            return self.hardware.ram_available_gb
        return 16.0

    def _persist_candidates(self, candidates: list[ModelCandidate]) -> None:
        with self._connect() as conn:
            for c in candidates:
                conn.execute(
                    """INSERT INTO meta_model_candidates
                       (model_name, size_bytes, parameter_count, description,
                        source_url, compatible, estimated_vram_gb, status, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'discovered', ?)
                       ON CONFLICT(model_name) DO UPDATE SET
                        size_bytes=excluded.size_bytes,
                        compatible=excluded.compatible,
                        estimated_vram_gb=excluded.estimated_vram_gb,
                        status='discovered'""",
                    (c.name, c.size_bytes, c.parameter_count, c.description,
                     c.source_url, int(c.compatible), c.estimated_vram_gb,
                     datetime.now(timezone.utc).isoformat()),
                )

    # ---- Evaluation -------------------------------------------------------

    def evaluate_candidate(
        self,
        candidate_name: str,
        test_tasks: dict[str, str] | None = None,
    ) -> ModelEvaluation:
        tasks = test_tasks or DEFAULT_BENCHMARK_PROMPTS
        scores: list[float] = []
        total_latency = 0
        notes_parts: list[str] = []

        for task_type, prompt in tasks.items():
            start = time.perf_counter()
            result = self._run_benchmark(candidate_name, prompt)
            latency_ms = int((time.perf_counter() - start) * 1000)
            total_latency += latency_ms
            score = self._score_response(result, prompt)
            scores.append(score)
            notes_parts.append(f"{task_type}={score:.3f}")

        avg_score = round(sum(scores) / len(scores), 3) if scores else 0.0
        avg_latency = total_latency // len(tasks) if tasks else 0
        quality_notes = "; ".join(notes_parts)

        evaluation = ModelEvaluation(
            model_name=candidate_name,
            task_type="composite",
            score=avg_score,
            latency_ms=avg_latency,
            quality_notes=quality_notes,
        )

        self._store_evaluation(evaluation)
        return evaluation

    def _run_benchmark(self, model: str, prompt: str) -> str:
        if self.model_client and hasattr(self.model_client, "generate"):
            result = self.model_client.generate(model=model, prompt=prompt)
            if hasattr(result, "text"):
                return result.text if result.ok else ""
            return ""
        data = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{self.OLLAMA_BASE_URL}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
                return str(body.get("response", "")).strip()
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return ""

    def _score_response(self, output: str, prompt: str) -> float:
        if not output:
            return 0.1
        score = 0.3
        if len(output) > 50:
            score += 0.15
        if len(output) > 200:
            score += 0.1
        prompt_words = set(prompt.lower().split())
        overlap = sum(1 for w in prompt_words if w in output.lower())
        if overlap > 3:
            score += 0.15
        coherence = ["porque", "por lo tanto", "sin embargo", "therefore", "however", "because"]
        if any(s in output.lower() for s in coherence):
            score += 0.1
        if len(output) > 500 and output.count("\n") > 2:
            score += 0.1
        return round(min(1.0, max(0.0, score)), 3)

    def _store_evaluation(self, evaluation: ModelEvaluation) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO meta_model_evaluations
                   (model_name, task_type, score, latency_ms, quality_notes, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (evaluation.model_name, evaluation.task_type, evaluation.score,
                 evaluation.latency_ms, evaluation.quality_notes, evaluation.created_at),
            )

    # ---- Decision ---------------------------------------------------------

    def decide(
        self,
        candidate_name: str,
        current_model_name: str,
        current_score: float,
        new_score: float,
    ) -> ModelDecision:
        improvement_pct = 0.0
        if current_score > 0:
            improvement_pct = round(((new_score - current_score) / current_score) * 100, 2)

        candidate_size = self._get_candidate_size(candidate_name)
        is_small = candidate_size <= self.SMALL_MODEL_MAX_BYTES if candidate_size else False

        if improvement_pct > self.ADOPT_THRESHOLD_PCT:
            decision = "adopt"
            reason = f"Improvement {improvement_pct:.1f}% exceeds {self.ADOPT_THRESHOLD_PCT}% threshold."
        elif improvement_pct > self.ADOPT_SMALL_THRESHOLD_PCT and is_small:
            decision = "adopt"
            reason = (
                f"Improvement {improvement_pct:.1f}% exceeds {self.ADOPT_SMALL_THRESHOLD_PCT}% "
                f"threshold and model is small ({candidate_size / 1024**3:.1f}GB)."
            )
        elif improvement_pct < -5.0:
            decision = "reject"
            reason = f"Performance degraded by {abs(improvement_pct):.1f}%."
        else:
            decision = "monitor"
            reason = (
                f"Improvement {improvement_pct:.1f}% is within acceptable range; "
                "monitoring further."
            )

        model_decision = ModelDecision(
            model_name=candidate_name,
            decision=decision,
            reason=reason,
            previous_model=current_model_name,
            improvement_pct=improvement_pct,
        )

        self._store_decision(model_decision)
        return model_decision

    def _get_candidate_size(self, model_name: str) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT size_bytes FROM meta_model_candidates WHERE model_name = ?",
                (model_name,),
            ).fetchone()
            return int(row["size_bytes"]) if row else None

    def _store_decision(self, decision: ModelDecision) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO meta_model_decisions
                   (model_name, decision, reason, previous_model, improvement_pct, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (decision.model_name, decision.decision, decision.reason,
                 decision.previous_model, decision.improvement_pct, decision.created_at),
            )
            if decision.decision == "adopt":
                conn.execute(
                    "UPDATE meta_model_candidates SET status = 'adopted' WHERE model_name = ?",
                    (decision.model_name,),
                )
            elif decision.decision == "reject":
                conn.execute(
                    "UPDATE meta_model_candidates SET status = 'rejected' WHERE model_name = ?",
                    (decision.model_name,),
                )

    # ---- Adoption / rollback ----------------------------------------------

    def adopt_model(self, model_name: str, task_type: str) -> bool:
        pulled = self._ollama_pull(model_name)
        if not pulled:
            return False
        with self._connect() as conn:
            conn.execute(
                "UPDATE meta_model_candidates SET status = 'adopted' WHERE model_name = ?",
                (model_name,),
            )
        return True

    def rollback_model(self, task_type: str, previous_model: str) -> bool:
        installed = self._get_installed_models()
        if previous_model not in installed:
            return False
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO meta_model_decisions
                   (model_name, decision, reason, previous_model, improvement_pct, created_at)
                   VALUES (?, 'rollback', ?, ?, 0.0, ?)""",
                (previous_model,
                 f"Rollback for task_type={task_type}",
                 previous_model,
                 datetime.now(timezone.utc).isoformat()),
            )
        return True

    @staticmethod
    def _ollama_pull(model_name: str) -> bool:
        try:
            result = subprocess.run(
                ["ollama", "pull", model_name],
                check=False,
                capture_output=True,
                text=True,
                timeout=600,
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    # ---- Queries ----------------------------------------------------------

    def get_adoption_history(self) -> list[ModelDecision]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM meta_model_decisions ORDER BY id DESC"
            ).fetchall()
        return [
            ModelDecision(
                model_name=r["model_name"],
                decision=r["decision"],
                reason=r["reason"],
                previous_model=r["previous_model"],
                improvement_pct=float(r["improvement_pct"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def get_model_scores(self) -> dict[str, dict[str, float]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT model_name, task_type, AVG(score) as avg_score,
                          COUNT(*) as eval_count
                   FROM meta_model_evaluations
                   GROUP BY model_name, task_type"""
            ).fetchall()
        result: dict[str, dict[str, float]] = {}
        for r in rows:
            model = r["model_name"]
            result.setdefault(model, {})[r["task_type"]] = round(float(r["avg_score"]), 3)
        return result

    def get_active_models(self) -> dict[str, str]:
        scores = self.get_model_scores()
        active: dict[str, str] = {}
        for model, task_scores in scores.items():
            for task_type, score in task_scores.items():
                if task_type not in active or score > scores.get(active[task_type], {}).get(task_type, 0.0):
                    active[task_type] = model
        return active

    # ---- Monitoring -------------------------------------------------------

    def monitor_adoption(self, model_name: str, days: int = 7) -> dict[str, Any]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT score, latency_ms, created_at
                   FROM meta_model_evaluations
                   WHERE model_name = ? AND created_at >= ?
                   ORDER BY created_at DESC""",
                (model_name, cutoff),
            ).fetchall()

        if not rows:
            return {
                "model_name": model_name,
                "status": "no_data",
                "message": f"No evaluations found in the last {days} days.",
                "sample_count": 0,
            }

        scores = [float(r["score"]) for r in rows]
        latencies = [int(r["latency_ms"]) for r in rows]
        avg_score = round(sum(scores) / len(scores), 3)
        avg_latency = round(sum(latencies) / len(latencies))
        min_score = round(min(scores), 3)
        max_score = round(max(scores), 3)
        trend = "improving" if len(scores) >= 2 and scores[0] > scores[-1] else (
            "declining" if len(scores) >= 2 and scores[0] < scores[-1] else "stable"
        )

        status = "healthy"
        if avg_score < 0.3:
            status = "degraded"
        elif trend == "declining" and avg_score < 0.5:
            status = "warning"

        return {
            "model_name": model_name,
            "status": status,
            "period_days": days,
            "sample_count": len(rows),
            "avg_score": avg_score,
            "min_score": min_score,
            "max_score": max_score,
            "avg_latency_ms": avg_latency,
            "trend": trend,
        }

    # ---- Cleanup ----------------------------------------------------------

    def cleanup_old_models(self, keep_count: int = 3) -> int:
        with self._connect() as conn:
            active_rows = conn.execute(
                """SELECT model_name FROM meta_model_decisions
                   WHERE decision = 'adopt'
                   GROUP BY model_name
                   ORDER BY MAX(id) DESC
                   LIMIT ?""",
                (keep_count,),
            ).fetchall()
            active_names = {r["model_name"] for r in active_rows}

            adopted_rows = conn.execute(
                """SELECT model_name FROM meta_model_candidates
                   WHERE status = 'adopted'"""
            ).fetchall()
            adopted_names = {r["model_name"] for r in adopted_rows}

            removable = adopted_names - active_names

        removed = 0
        for model_name in removable:
            if self._ollama_remove(model_name):
                with self._connect() as conn:
                    conn.execute(
                        "UPDATE meta_model_candidates SET status = 'removed' WHERE model_name = ?",
                        (model_name,),
                    )
                removed += 1
        return removed

    @staticmethod
    def _ollama_remove(model_name: str) -> bool:
        try:
            result = subprocess.run(
                ["ollama", "rm", model_name],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

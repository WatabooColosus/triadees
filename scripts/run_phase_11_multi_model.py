#!/usr/bin/env python3
"""A/B real y reproducible: routing por rol contra un único modelo Ollama."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from triade.models.measured_orchestration import (
    MeasuredModelOrchestrator,
    MeasuredRoute,
)
from triade.runtime.task_artifacts import AtomicArtifactWriter

OLLAMA = "http://127.0.0.1:11434"
BASELINE = "qwen3:4b"
ROUTES = {
    "planner": "qwen3:4b",
    "coder": "qwen2.5-coder:3b",
    "critic": "qwen3:4b",
    "evaluator": "qwen3:4b",
    "embedding": "nomic-embed-text:latest",
    "vision": "gemma3:4b",
    "summarizer": "qwen3:1.7b",
}
TASKS = {
    "planner": (
        "Devuelve solo JSON con keys steps (lista) y rollback (string). Planifica "
        "una migración SQLite reversible con backup, validación y restauración."
    ),
    "coder": (
        "Devuelve solo JSON con keys code y invariant. Escribe una función Python "
        "idempotente que inserte una clave solo si no existe."
    ),
    "critic": (
        "Devuelve solo JSON con keys issues (lista) y severity. Revisa: "
        "'except Exception: return True' y explica el falso éxito."
    ),
    "evaluator": (
        "Devuelve solo JSON con keys score (0..1) y reasons (lista). Evalúa una "
        "ejecución sin recibo de efecto ni artefacto."
    ),
    "summarizer": (
        "Devuelve solo JSON con keys summary y facts (lista). Resume sin inventar: "
        "'La tarea 7 expiró; fencing 3 rechazó el resultado tardío; no hubo efecto'."
    ),
}
REQUIRED_KEYS = {
    "planner": {"steps", "rollback"},
    "coder": {"code", "invariant"},
    "critic": {"issues", "severity"},
    "evaluator": {"score", "reasons"},
    "summarizer": {"summary", "facts"},
}
RED_PIXEL_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR42mP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"


@dataclass(slots=True)
class Measurement:
    role: str
    model: str
    status: str
    quality: float
    latency_ms: float
    peak_ram_mb: float
    peak_vram_mb: float
    output: str
    error: str | None = None

    @property
    def resource_cost(self) -> float:
        return round(
            self.latency_ms + self.peak_ram_mb * 0.01 + self.peak_vram_mb * 0.1,
            3,
        )


def _request(path: str, payload: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{OLLAMA}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        decoded = json.loads(response.read())
    return decoded if isinstance(decoded, dict) else {}


def installed_models() -> tuple[list[str], str | None]:
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=3) as response:
            payload = json.loads(response.read())
        return [item["name"] for item in payload.get("models", [])], None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return [], f"{type(exc).__name__}: {exc}"


def _gpu_used_mb() -> float:
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=memory.used",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        return 0.0
    values = [
        float(item.strip()) for item in result.stdout.splitlines() if item.strip()
    ]
    return sum(values)


def _ollama_ram_mb() -> float:
    try:
        import psutil

        return round(
            sum(
                process.memory_info().rss
                for process in psutil.process_iter(["name"])
                if "ollama" in str(process.info.get("name") or "").lower()
            )
            / 1024**2,
            3,
        )
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
        return 0.0


def _measure_call(call: Any) -> tuple[dict[str, Any], float, float, float]:
    stop = threading.Event()
    peaks = {"ram": _ollama_ram_mb(), "vram": _gpu_used_mb()}

    def sample() -> None:
        while not stop.wait(0.05):
            peaks["ram"] = max(peaks["ram"], _ollama_ram_mb())
            peaks["vram"] = max(peaks["vram"], _gpu_used_mb())

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    started = time.perf_counter()
    try:
        result = call()
    finally:
        elapsed = (time.perf_counter() - started) * 1000
        stop.set()
        sampler.join(timeout=2)
    return result, round(elapsed, 3), peaks["ram"], peaks["vram"]


def _json_quality(role: str, output: str) -> float:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return 0.0
    if not isinstance(payload, dict):
        return 0.0
    required = REQUIRED_KEYS[role]
    present = sum(key in payload for key in required) / len(required)
    nonempty = sum(bool(payload.get(key)) for key in required) / len(required)
    return round(0.5 * present + 0.5 * nonempty, 4)


def run_text(role: str, model: str) -> Measurement:
    try:
        response, latency, ram, vram = _measure_call(
            lambda: _request(
                "/api/generate",
                {
                    "model": model,
                    "prompt": TASKS[role],
                    "format": "json",
                    "think": False,
                    "stream": False,
                    "options": {"temperature": 0, "seed": 17, "num_predict": 256},
                    "keep_alive": 0,
                },
            )
        )
        output = str(response.get("response") or "")
        return Measurement(
            role, model, "ok", _json_quality(role, output), latency, ram, vram, output
        )
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return Measurement(role, model, "error", 0.0, 0.0, 0.0, 0.0, "", str(exc))


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    denominator = math.sqrt(sum(a * a for a in left)) * math.sqrt(
        sum(b * b for b in right)
    )
    return numerator / denominator if denominator else 0.0


def run_embedding(model: str) -> Measurement:
    texts = ["rollback de base de datos", "restaurar backup SQLite", "receta de cocina"]
    try:
        response, latency, ram, vram = _measure_call(
            lambda: _request(
                "/api/embed", {"model": model, "input": texts, "keep_alive": 0}
            )
        )
        embeddings = response.get("embeddings") or []
        quality = 0.0
        if len(embeddings) == 3:
            related = _cosine(embeddings[0], embeddings[1])
            unrelated = _cosine(embeddings[0], embeddings[2])
            quality = 1.0 if related > unrelated else 0.0
        return Measurement(
            "embedding", model, "ok", quality, latency, ram, vram, "semantic_ranking"
        )
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return Measurement(
            "embedding", model, "unavailable", 0.0, 0.0, 0.0, 0.0, "", str(exc)
        )


def run_vision(model: str) -> Measurement:
    try:
        response, latency, ram, vram = _measure_call(
            lambda: _request(
                "/api/generate",
                {
                    "model": model,
                    "prompt": "Devuelve solo JSON con key color para el color dominante.",
                    "images": [RED_PIXEL_PNG],
                    "format": "json",
                    "think": False,
                    "stream": False,
                    "options": {"temperature": 0, "seed": 17, "num_predict": 64},
                    "keep_alive": 0,
                },
            )
        )
        output = str(response.get("response") or "")
        try:
            color = str(json.loads(output).get("color") or "").lower()
        except (json.JSONDecodeError, AttributeError):
            color = ""
        quality = 1.0 if color in {"red", "rojo"} else 0.0
        return Measurement("vision", model, "ok", quality, latency, ram, vram, output)
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return Measurement("vision", model, "error", 0.0, 0.0, 0.0, 0.0, "", str(exc))


def run_role(role: str, model: str) -> Measurement:
    if role == "embedding":
        return run_embedding(model)
    if role == "vision":
        return run_vision(model)
    return run_text(role, model)


def aggregate(measurements: list[Measurement]) -> dict[str, float]:
    count = max(1, len(measurements))
    return {
        "quality": round(sum(item.quality for item in measurements) / count, 4),
        "latency_ms": round(sum(item.latency_ms for item in measurements) / count, 3),
        "peak_ram_mb": round(
            max((item.peak_ram_mb for item in measurements), default=0), 3
        ),
        "peak_vram_mb": round(
            max((item.peak_vram_mb for item in measurements), default=0), 3
        ),
        "resource_cost": round(
            sum(item.resource_cost for item in measurements) / count, 3
        ),
    }


def main() -> int:
    models, error = installed_models()
    required = {BASELINE, *ROUTES.values()}
    missing = sorted(required - set(models))
    if error or missing:
        report = {
            "phase": 11,
            "ollama_models": models,
            "provider_error": error,
            "missing_models": missing,
            "real_ab_executed": False,
            "routing_adopted": False,
            "runtime_verified": False,
            "status": "partial",
            "reason": "real_models_unavailable",
        }
    else:
        baseline: list[Measurement] = []
        candidate: list[Measurement] = []
        for role, candidate_model in ROUTES.items():
            baseline_result = run_role(role, BASELINE)
            baseline.append(baseline_result)
            candidate.append(
                baseline_result
                if candidate_model == BASELINE
                else run_role(role, candidate_model)
            )
        baseline_metrics = aggregate(baseline)
        candidate_metrics = aggregate(candidate)
        routes = [
            MeasuredRoute(
                f"ab-{role}", role, model, "measured_role_candidate", False, False
            )
            for role, model in ROUTES.items()
        ]
        with tempfile.TemporaryDirectory() as directory:
            orchestrator = MeasuredModelOrchestrator(Path(directory) / "triade.db", [])
            decision = orchestrator.evaluate_adoption(
                baseline_model=BASELINE,
                routes=routes,
                baseline_metrics={
                    "quality": baseline_metrics["quality"],
                    "resource_cost": baseline_metrics["resource_cost"],
                },
                candidate_metrics={
                    "quality": candidate_metrics["quality"],
                    "resource_cost": candidate_metrics["resource_cost"],
                },
            )
        report = {
            "phase": 11,
            "ollama_models": models,
            "baseline_model": BASELINE,
            "candidate_routes": ROUTES,
            "benchmark_seed": 17,
            "evaluation": "deterministic_contract_and_semantic_ranking",
            "baseline": [
                asdict(item) | {"resource_cost": item.resource_cost}
                for item in baseline
            ],
            "candidate": [
                asdict(item) | {"resource_cost": item.resource_cost}
                for item in candidate
            ],
            "baseline_metrics": baseline_metrics,
            "candidate_metrics": candidate_metrics,
            "real_ab_executed": True,
            "routing_adopted": decision["adopted"],
            "rollback_ref": decision["rollback_ref"],
            "adoption_reason": decision["reason"],
            "runtime_verified": all(item.status == "ok" for item in candidate),
            "status": "completed" if decision["adopted"] else "partial",
            "reason": decision["reason"],
        }
    output = Path("artifacts/triade_verify/phase_11/multi_model.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if report.get("routing_adopted"):
        benchmark_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
        active = {
            "version": 1,
            "status": "active",
            "baseline_model": BASELINE,
            "routes": ROUTES,
            "benchmark_sha256": benchmark_sha256,
            "evidence_ref": str(output),
            "rollback_ref": "triade/models/active_routing.rollback.json",
        }
        rollback = {
            "version": 1,
            "status": "rollback_baseline",
            "baseline_model": BASELINE,
            "routes": {role: BASELINE for role in ROUTES},
            "evidence_ref": str(output),
        }
        AtomicArtifactWriter.write_json(
            Path("triade/models/active_routing.json"), active
        )
        AtomicArtifactWriter.write_json(
            Path("triade/models/active_routing.rollback.json"), rollback
        )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

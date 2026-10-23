"""Benchmark reproducible del camino mínimo sin cargar modelos adicionales."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from triade.models.hardware_profile import HardwareProfiler
from triade.models.model_client_factory import create_model_client


def _rss_mb() -> float | None:
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / 1024**2, 2)
    except ImportError:
        return None


def run(
    model: str | None = None, prompt: str = "Responde únicamente: OK"
) -> dict[str, Any]:
    provider = os.getenv("TRIADE_MODEL_PROVIDER", "ollama")
    client = create_model_client(
        provider, timeout=int(os.getenv("TRIADE_MODEL_TIMEOUT", "120"))
    )
    started = time.perf_counter()
    health = client.health()
    health_ms = round((time.perf_counter() - started) * 1000, 2)
    selected = (
        model
        or (health.get("models") or [os.getenv("TRIADE_LLAMA_CPP_MODEL", "unknown")])[0]
    )
    before = _rss_mb()
    started = time.perf_counter()
    result = (
        client.generate(selected, prompt, options={"temperature": 0, "num_predict": 32})
        if health.get("ok")
        else None
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    after = _rss_mb()
    return {
        "status": "ok" if result and result.ok else "degraded",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "provider": provider,
        "model": selected,
        "hardware": HardwareProfiler().detect().to_dict(),
        "health": health,
        "health_latency_ms": health_ms,
        "generation_latency_ms": latency_ms,
        "rss_before_mb": before,
        "rss_after_mb": after,
        "rss_delta_mb": round(after - before, 2)
        if before is not None and after is not None
        else None,
        "tokens": getattr(result, "eval_count", None) if result else None,
        "error": getattr(result, "error", None) if result else health.get("error"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = run(args.model)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

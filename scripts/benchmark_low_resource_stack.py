#!/usr/bin/env python3
"""Benchmark reproducible del perfil 8GB-first de Tríade Ω."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import psutil

from triade.core.resource_probe import build_resource_probe
from triade.models.model_client_factory import (
    build_model_client,
    default_model_base_url,
    normalize_model_provider,
)


def _snapshot(label: str) -> dict[str, Any]:
    process = psutil.Process()
    probe = build_resource_probe()
    devices = (
        probe.get("gpu", {})
        .get("telemetry", {})
        .get("devices", [])
    )
    return {
        "label": label,
        "process_rss_mb": round(process.memory_info().rss / (1024 * 1024), 2),
        "system_ram_available_gb": probe.get("memory", {}).get("available_gb"),
        "system_ram_used_percent": probe.get("memory", {}).get("used_percent"),
        "gpu_devices": [
            {
                "total_mib": item.get("total_mib"),
                "free_mib": item.get("free_mib"),
                "utilization_percent": item.get("utilization_percent"),
                "temperature_celsius": item.get("temperature_celsius"),
            }
            for item in devices
        ],
        "hardware_tier": probe.get("hardware", {}).get("tier"),
        "warnings": probe.get("warnings", []),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="ollama")
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--prompt", default="Responde sólo: TRIADA_OK")
    parser.add_argument("--num-predict", type=int, default=32)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    provider = normalize_model_provider(args.provider)
    base_url = args.base_url or default_model_base_url(provider)
    before = _snapshot("before")
    client = build_model_client(provider, base_url=base_url, timeout=120)

    if client is None:
        payload = {
            "status": "error",
            "error": f"unsupported_provider:{provider}",
            "before": before,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 2

    health_started = time.perf_counter()
    health = client.health()
    health_ms = round((time.perf_counter() - health_started) * 1000, 2)

    generation: dict[str, Any] | None = None
    if args.model and health.get("ok"):
        started = time.perf_counter()
        result = client.generate(
            args.model,
            args.prompt,
            options={"temperature": 0, "num_predict": max(1, args.num_predict)},
            keep_alive=0,
        )
        generation = {
            "ok": result.ok,
            "provider": result.provider,
            "model": result.model,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "prompt_tokens": result.prompt_eval_count,
            "completion_tokens": result.eval_count,
            "error": result.error,
        }

    after = _snapshot("after")
    payload = {
        "status": "ok",
        "profile": "triade-8gb-first-v1",
        "provider": provider,
        "base_url": base_url,
        "health": {
            "ok": health.get("ok"),
            "latency_ms": health_ms,
            "models": health.get("models", []),
            "error": health.get("error"),
        },
        "generation": generation,
        "before": before,
        "after": after,
        "delta": {
            "process_rss_mb": round(
                float(after["process_rss_mb"]) - float(before["process_rss_mb"]), 2
            ),
            "system_ram_available_gb": (
                round(
                    float(after["system_ram_available_gb"])
                    - float(before["system_ram_available_gb"]),
                    3,
                )
                if before["system_ram_available_gb"] is not None
                and after["system_ram_available_gb"] is not None
                else None
            ),
        },
        "acceptance": {
            "one_model_at_a_time": True,
            "context_target_tokens": 4096,
            "core_requires_torch": False,
            "core_requires_redis": False,
            "stable_consolidation_on_low_tier": False,
        },
    }

    rendered = json.dumps(payload, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

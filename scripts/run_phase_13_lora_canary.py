#!/usr/bin/env python3
"""Verifica artifacts PEFT reales sin activarlos sin aprobación nominal."""

import json
from pathlib import Path

from triade.training.peft_canary import PeftCanaryServer
from triade.training.serving_governance import (
    GovernedPeftServing,
    build_integrity_bundle,
)


def main() -> int:
    adapter = Path("artifacts/adapters/triade-continuity-canary").resolve()
    bundle = build_integrity_bundle(adapter)
    serving = GovernedPeftServing("triade/memory/triade.db", "artifacts/adapters")
    enrolled = serving.enroll(adapter, traffic_percent=5)
    generation = PeftCanaryServer(
        "triade/memory/triade.db", "artifacts/adapters"
    ).generate(str(adapter), "Responde exactamente: canary-ok", max_new_tokens=48)
    observed = serving.observe(
        enrolled["version_id"],
        quality=1.0
        if generation.get("status") == "completed" and generation.get("response")
        else -10.0,
        latency_ms=float(generation.get("latency_ms") or 0),
        success=generation.get("status") == "completed",
        evidence_ref="phase13:real-peft-generation",
    )
    activation = serving.activate(enrolled["version_id"], approved_by="")
    report = {
        "phase": 13,
        "integrity_bundle_sha256": bundle["bundle_sha256"],
        "enrollment": enrolled,
        "real_canary": generation,
        "observation": observed,
        "activation": activation,
        "automatic_activation": False,
        "status": "partial",
        "pending": ["named_human_approval", "controlled_production_traffic"],
    }
    output = Path("artifacts/triade_verify/phase_13/lora_canary.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return (
        0
        if generation.get("status") == "completed" and activation["status"] == "blocked"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Ejecuta el benchmark ablativo reproducible de la Fase 4."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from triade.core.runner import TriadeRunner
from triade.evaluation.triadic_ablation import run_triadic_ablation_benchmark


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/triade_verify/phase_04/triadic_causality.json",
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="triade-phase04-") as raw_tmp:
        root = Path(raw_tmp)
        runtime = TriadeRunner(
            db_path=root / "runtime.db",
            runs_dir=root / "runs",
            use_ollama=False,
        ).run(
            "Verifica de forma prudente la continuidad del proyecto Atlas.",
            semantic_recall_enabled=False,
            propose_neurons=False,
        )
        run_path = Path(runtime["run_path"])
        trace = json.loads(
            (run_path / "triadic_cycle_trace.json").read_text(encoding="utf-8")
        )
        trace_verification = json.loads(
            (run_path / "triadic_cycle_trace_verification.json").read_text(
                encoding="utf-8"
            )
        )
        benchmark = run_triadic_ablation_benchmark(root / "ablation.db")
        payload = {
            "phase": 4,
            "generated_at": datetime.now(UTC).isoformat(),
            "runtime_trace": {
                "run_id": runtime["run_id"],
                "verification": trace_verification,
                "components": sorted(trace["component_contribution"]),
                "degraded_components": trace["degraded_components"],
            },
            "ablation": benchmark,
            "passed": trace_verification["status"] == "verified"
            and benchmark["passed"],
        }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

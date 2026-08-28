#!/usr/bin/env python3
"""Genera evidencia runtime de memoria longitudinal para TRIADE-VERIFY."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from triade.evaluation.memory_longitudinal import (
    run_memory_longitudinal_benchmark,
)

TRIADE_ENTRYPOINT_KIND = "manual_diagnostic"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/triade_verify/phase_05/memory_longitudinal.json",
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="triade-phase05-") as raw_tmp:
        benchmark = run_memory_longitudinal_benchmark(Path(raw_tmp))
    payload = {
        "phase": 5,
        "generated_at": datetime.now(UTC).isoformat(),
        **benchmark,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

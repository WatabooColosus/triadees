"""Ejecuta y persiste el experimento reproducible de la Fase 1."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from triade.learning.context_selection_benchmark import run_phase_1_experiment


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--benchmark-dir",
        type=Path,
        default=repo_root / "benchmarks/learning/context_selection/v1",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="Directorio persistente opcional; por defecto cada run queda aislado.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/evolution/phase_1_results.json"),
    )
    args = parser.parse_args()
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo_root,
    ).stdout.strip()
    if args.work_dir is None:
        with tempfile.TemporaryDirectory(prefix="triade-phase-1-") as work_dir:
            result = run_phase_1_experiment(
                args.benchmark_dir, work_dir=work_dir, sha=sha
            )
    else:
        result = run_phase_1_experiment(
            args.benchmark_dir, work_dir=args.work_dir, sha=sha
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["closure"], ensure_ascii=False, sort_keys=True))
    return 0 if all(result["closure"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

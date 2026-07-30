#!/usr/bin/env python3
"""Ejecuta exactamente 24 horas wall-clock; no comprime el tiempo."""

import argparse

from triade.validation.runtime_long_run import run_wall_clock_validation, write_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=int, default=86_400)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument(
        "--report", default="runs/triade_verify_live/phase_17/runtime_24h.json"
    )
    args = parser.parse_args()
    report = run_wall_clock_validation(
        duration_seconds=args.duration_seconds,
        interval_seconds=args.interval_seconds,
        db_path="triade/memory/triade.db",
        web_url="http://127.0.0.1:8010/health/live",
        ollama_url="http://127.0.0.1:11434/api/tags",
    )
    report["window"] = "24h" if args.duration_seconds == 86_400 else "short_validation"
    write_report(report, args.report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

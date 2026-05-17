#!/usr/bin/env python3
"""Launcher CLI inicial para Tríade Ω Digimon."""

from __future__ import annotations

import argparse
import json

from triade.core.runner import TriadeRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Tríade Ω · MVP local auditable")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Ejecuta un mensaje como run auditable")
    run_parser.add_argument("text", help="Texto de entrada para Tríade")
    run_parser.add_argument("--runs-dir", default="runs", help="Carpeta donde se guardan runs")

    args = parser.parse_args()

    if args.command == "run":
        runner = TriadeRunner(runs_dir=args.runs_dir)
        result = runner.run(args.text)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Backfill seguro de misiones neuronales desde neuronas existentes."""

from __future__ import annotations

import argparse
import json
import sys

from triade.workers.neuron_mission_backfill import backfill_neuron_missions, neuron_missions_doctor


def _print_json(payload: object) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill de misiones neuronales")
    parser.add_argument("--db", default="triade/memory/triade.db", help="Ruta de la base SQLite")
    parser.add_argument("--runs-dir", default="runs", help="Directorio de runs para evidencia")
    parser.add_argument("--limit", type=int, default=500, help="Límite de neuronas/misiones a inspeccionar")
    parser.add_argument("command", choices=["backfill", "doctor"], help="Acción a ejecutar")
    args = parser.parse_args()

    if args.command == "backfill":
        _print_json(backfill_neuron_missions(db_path=args.db, runs_dir=args.runs_dir, limit=args.limit))
        return
    _print_json(neuron_missions_doctor(db_path=args.db, runs_dir=args.runs_dir, limit=args.limit))


if __name__ == "__main__":
    main()

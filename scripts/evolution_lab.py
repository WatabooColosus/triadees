#!/usr/bin/env python3
"""CLI administrativa para el laboratorio de evolución gobernada."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from triade.evolution import EvolutionLab, Stage


def load_json(value: str) -> Any:
    path = Path(value)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(value)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Tríade Ω Evolution Lab")
    root.add_argument("--db", default="triade/memory/triade.db")
    commands = root.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create")
    create.add_argument("--title", required=True)
    create.add_argument("--hypothesis", required=True)
    create.add_argument("--baseline", required=True)
    create.add_argument("--candidate", required=True)

    show = commands.add_parser("show")
    show.add_argument("campaign_id")
    freeze = commands.add_parser("freeze")
    freeze.add_argument("campaign_id")
    freeze.add_argument("cases")
    evidence = commands.add_parser("evidence")
    evidence.add_argument("campaign_id")
    evidence.add_argument("--stage", type=int, choices=range(1, 7), required=True)
    evidence.add_argument("--kind", required=True)
    evidence.add_argument("--payload", required=True)
    evidence.add_argument("--source", required=True)
    evidence.add_argument("--independent", action="store_true")
    artifact = commands.add_parser("artifact")
    artifact.add_argument("campaign_id")
    artifact.add_argument("--kind", required=True)
    artifact.add_argument("--path", required=True)
    artifact.add_argument("--parent-sha256")
    charge = commands.add_parser("charge")
    charge.add_argument("campaign_id")
    charge.add_argument("--gpu-minutes", type=float, default=0)
    charge.add_argument("--experiments", type=int, default=0)
    charge.add_argument("--storage-mb", type=float, default=0)
    for name in ("evaluate", "advance", "report"):
        sub = commands.add_parser(name)
        sub.add_argument("campaign_id")
    reject = commands.add_parser("reject")
    reject.add_argument("campaign_id")
    reject.add_argument("--reason", required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    lab = EvolutionLab(args.db)
    if args.command == "create":
        result = lab.create_campaign(
            args.title, args.hypothesis, args.baseline, args.candidate
        )
    elif args.command == "show":
        result = lab.campaign(args.campaign_id)
    elif args.command == "freeze":
        result = lab.freeze_battery(args.campaign_id, load_json(args.cases))
    elif args.command == "evidence":
        result = lab.record_evidence(
            args.campaign_id,
            Stage(args.stage),
            args.kind,
            load_json(args.payload),
            source=args.source,
            independent=args.independent,
        )
    elif args.command == "artifact":
        result = lab.register_artifact(
            args.campaign_id, args.kind, args.path, parent_sha256=args.parent_sha256
        )
    elif args.command == "charge":
        result = lab.charge_resources(
            args.campaign_id,
            gpu_minutes=args.gpu_minutes,
            experiments=args.experiments,
            storage_mb=args.storage_mb,
        )
    elif args.command == "evaluate":
        decision = lab.evaluate_stage(args.campaign_id)
        result = lab._decision_dict(decision)
    elif args.command == "advance":
        result = lab.advance(args.campaign_id)
    elif args.command == "report":
        result = lab.report(args.campaign_id)
    else:
        result = lab.reject(args.campaign_id, args.reason)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

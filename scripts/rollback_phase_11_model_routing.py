#!/usr/bin/env python3
"""Restaura explícitamente el baseline monomodelo medido de la fase 11."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from triade.runtime.task_artifacts import AtomicArtifactWriter


def rollback_routing(active: Path, rollback: Path) -> dict[str, str]:
    payload = json.loads(rollback.read_text(encoding="utf-8"))
    if payload.get("status") != "rollback_baseline":
        raise RuntimeError("invalid_model_routing_rollback")
    AtomicArtifactWriter.write_json(active, payload)
    return {"status": "rolled_back", "active": str(active)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--active", default="triade/models/active_routing.json", type=Path
    )
    parser.add_argument(
        "--rollback", default="triade/models/active_routing.rollback.json", type=Path
    )
    args = parser.parse_args()
    print(json.dumps(rollback_routing(args.active, args.rollback)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

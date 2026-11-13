#!/usr/bin/env python3
"""Evidencia runtime determinista para research gobernado."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from triade.research.governed import GovernedResearchWorker


def _source(host: str, value: str = "supported") -> dict:
    return {
        "url": f"https://{host}/evidence",
        "title": f"Evidence {host}",
        "content": f"Independent reproducible evidence: {value}",
        "claims": [{"key": "claim", "value": value}],
        "fetched_at": datetime.now(UTC).isoformat(),
    }


def _execute(root: Path, name: str, sources: list[dict], failures=None) -> dict:
    worker = GovernedResearchWorker(
        root / f"{name}.db",
        lambda question, minimum: {"sources": sources, "failures": failures or []},
    )
    return worker.run(
        question="Is the benchmark claim supported?",
        trigger="benchmark_need",
        scope="phase08",
        allowed_sources=["one.test", "two.test", "three.test"],
        unresolved_questions=["Does the result transfer outside this benchmark?"],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/triade_verify/phase_08/governed_research.json",
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="triade-phase08-") as raw_tmp:
        root = Path(raw_tmp)
        insufficient = _execute(root, "insufficient", [_source("one.test")])
        conflict = _execute(
            root,
            "conflict",
            [_source("one.test", "yes"), _source("two.test", "no")],
        )
        accepted = _execute(
            root,
            "accepted",
            [_source("one.test"), _source("two.test")],
            failures=[{"url": "https://three.test", "reason": "timeout"}],
        )
        checks = {
            "one_source_insufficient": insufficient["status"] == "insufficient_sources",
            "conflict_unresolved": conflict["status"] == "conflicting_sources"
            and conflict["contradictions"][0]["resolution"] == "unresolved",
            "independent_sources_candidate": accepted["status"] == "candidate_created",
            "source_failure_exposed": accepted["source_failures"][0]["reason"]
            == "timeout",
            "candidate_not_learning": accepted["learning_validated"] is False,
            "no_stable_memory": accepted["stable_memory_written"] is False,
        }
        payload = {
            "phase": 8,
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": checks,
            "runs": {
                "insufficient": insufficient,
                "conflicting": conflict,
                "candidate": accepted,
            },
            "passed": all(checks.values()),
        }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

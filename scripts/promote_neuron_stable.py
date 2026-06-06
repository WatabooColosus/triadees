from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from triade.core.neuron_registry import NeuronRegistry
from triade.core.stable_promotion_readiness import evaluate_stable_readiness


def load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_decision(path: Path, decision: dict[str, Any]) -> None:
    payload = load_json(path, [])
    if not isinstance(payload, list):
        payload = []
    payload.append(decision)
    write_json(path, payload)


def find_readiness(report: dict[str, Any], name: str) -> dict[str, Any] | None:
    for neuron in report.get("neurons") or []:
        if neuron.get("name") == name:
            return neuron
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Promotion Gate humano para promover neuronas experimentales a stable.")
    parser.add_argument("name", help="Nombre exacto de la neurona.")
    parser.add_argument("--db-path", default="triade/memory/triade.db")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--decisions-path", default="triade/runs/stable_promotion_decisions.json")
    parser.add_argument("--reason", default="")
    parser.add_argument("--confirm-human", action="store_true")
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--min-activations", type=int, default=5)
    parser.add_argument("--min-diagnosis", type=int, default=5)
    parser.add_argument("--min-test-plan", type=int, default=3)
    args = parser.parse_args()

    if not args.confirm_human:
        raise SystemExit("Bloqueado: promoción a stable requiere --confirm-human.")

    registry = NeuronRegistry(db_path=args.db_path)
    existing = registry.get_neuron(args.name)
    if not existing:
        raise SystemExit(f"No existe neurona registrada: {args.name}")

    if str(existing.get("status")) != "experimental":
        raise SystemExit(f"Bloqueado: solo se promueven neuronas experimental. Estado actual: {existing.get('status')}")

    report = evaluate_stable_readiness(
        runs_dir=args.runs_dir,
        limit=args.limit,
        thresholds={
            "min_activations": args.min_activations,
            "min_diagnosis": args.min_diagnosis,
            "min_test_plan": args.min_test_plan,
        },
    )

    readiness = find_readiness(report, args.name)
    if not readiness:
        raise SystemExit("Bloqueado: no hay evidencia experimental para esta neurona.")

    if not readiness.get("ready_for_stable_review"):
        decision = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "name": args.name,
            "decision": "blocked_not_ready",
            "previous_status": existing.get("status"),
            "next_status": existing.get("status"),
            "reason": args.reason,
            "readiness": readiness,
            "policy": "stable_requires_evidence_and_explicit_human_confirmation",
        }
        append_decision(Path(args.decisions_path), decision)
        print(json.dumps({
            "ok": False,
            "blocked": True,
            "decision": decision,
            "decisions_path": args.decisions_path,
        }, ensure_ascii=False, indent=2))
        return 2

    updated = registry.update_status(args.name, "stable")

    decision = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "name": args.name,
        "decision": "promote_to_stable",
        "previous_status": existing.get("status"),
        "next_status": "stable",
        "reason": args.reason,
        "readiness": readiness,
        "policy": "stable_requires_evidence_and_explicit_human_confirmation",
    }
    append_decision(Path(args.decisions_path), decision)

    print(json.dumps({
        "ok": True,
        "decision": decision,
        "updated": updated,
        "decisions_path": args.decisions_path,
    }, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

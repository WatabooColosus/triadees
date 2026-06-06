from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from triade.core.neuron_registry import NeuronRegistry


VALID_DECISIONS = {
    "approve": "experimental",
    "reject": "rejected",
    "request-changes": "needs_changes",
}


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


def latest_proposals(runs_dir: Path, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    run_dirs = sorted(
        [p for p in runs_dir.glob("run-*") if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )[:limit]

    seen: set[str] = set()

    for run_path in run_dirs:
        candidate = load_json(run_path / "neuron_candidate.json", {})
        if not isinstance(candidate, dict) or not candidate.get("name"):
            continue

        name = str(candidate["name"])
        if name in seen:
            continue
        seen.add(name)

        quality = candidate.get("proposal_quality") or {}
        assessment = candidate.get("assessment") or {}

        # Ignorar propuestas legacy sin contrato primario moderno.
        if candidate.get("policy") != "system_proposes_human_governs_no_auto_stable":
            continue
        if quality.get("contract_complete") is None:
            continue

        rows.append({
            "run_id": run_path.name,
            "name": name,
            "domain": candidate.get("domain"),
            "registered_as": candidate.get("registered_as"),
            "activation": candidate.get("activation"),
            "score": quality.get("score") or assessment.get("score"),
            "status": quality.get("status") or assessment.get("assessed_status"),
            "contract_complete": quality.get("contract_complete"),
            "required_human_review": quality.get("required_human_review"),
            "warnings": assessment.get("warnings") or [],
            "policy": candidate.get("policy"),
        })

    return rows


def append_decision(path: Path, decision: dict[str, Any]) -> None:
    payload = load_json(path, [])
    if not isinstance(payload, list):
        payload = []
    payload.append(decision)
    write_json(path, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Decision Gate humano para propuestas primarias de neuronas.")
    parser.add_argument("action", choices=["list", "approve", "reject", "request-changes"])
    parser.add_argument("name", nargs="?", default="")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--db-path", default="triade/memory/triade.db")
    parser.add_argument("--reason", default="")
    parser.add_argument("--decisions-path", default="triade/runs/primary_neuron_decisions.json")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)

    if args.action == "list":
        proposals = latest_proposals(runs_dir, limit=args.limit)
        print("=== PRIMARY NEURON DECISION GATE ===")
        if not proposals:
            print("No hay propuestas primarias recientes.")
            return 0

        for p in proposals:
            print(
                f'{p["name"]} | domain={p["domain"]} | '
                f'score={p["score"]} | status={p["status"]} | '
                f'contract_complete={p["contract_complete"]} | '
                f'human={p["required_human_review"]} | run={p["run_id"]}'
            )
            if p.get("warnings"):
                print("  warnings:", "; ".join(map(str, p["warnings"][:4])))
        return 0

    if not args.name:
        raise SystemExit("Debes indicar el nombre de la neurona.")

    target_status = VALID_DECISIONS[args.action]

    # Regla de seguridad: este script jamás promueve a stable.
    if target_status == "stable":
        raise SystemExit("Promoción a stable prohibida en este script.")

    registry = NeuronRegistry(db_path=args.db_path)
    existing = registry.get_neuron(args.name)
    if not existing:
        raise SystemExit(f"No existe neurona registrada: {args.name}")

    if str(existing.get("status")) == "stable":
        raise SystemExit("No se modifica una neurona stable desde este script.")

    updated = registry.update_status(args.name, target_status)

    decision = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "name": args.name,
        "decision": args.action,
        "next_status": target_status,
        "previous_status": existing.get("status"),
        "reason": args.reason,
        "policy": "human_decision_required_no_auto_stable",
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

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def classify(row: dict[str, Any]) -> str:
    warnings = " ".join(str(w) for w in (row.get("warnings") or [])).lower()
    score = float(row.get("score") or 0)

    if (
        "sin triggers" in warnings
        or "entradas/salidas" in warnings
        or "sin métricas" in warnings
        or "sin evidencia" in warnings
    ):
        return "needs_contract_completion"

    if score >= 0.8:
        return "ready_for_human_review"

    if score >= 0.55:
        return "candidate_keep_observing"

    return "reject_or_reformulate"


def main() -> int:
    parser = argparse.ArgumentParser(description="Construye bandeja de propuestas primarias de neuronas.")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--out", default="triade/runs/primary_neuron_proposal_inbox.json")
    parser.add_argument("--print", action="store_true")
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    run_dirs = sorted(
        [p for p in runs_dir.glob("run-*") if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )[: args.limit]

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for run_path in run_dirs:
        events = load_json(run_path / "system_events.json", [])
        if not isinstance(events, list):
            continue

        for event in events:
            if not isinstance(event, dict) or event.get("type") != "neuron_candidate_proposed":
                continue

            payload = event.get("payload") or {}
            assessment = payload.get("assessment") or {}
            name = str(payload.get("name") or "unknown")

            grouped[name].append({
                "run_id": run_path.name,
                "name": name,
                "neuron_id": payload.get("neuron_id"),
                "domain": payload.get("domain"),
                "registered_as": payload.get("registered_as"),
                "activation": payload.get("activation"),
                "score": assessment.get("score"),
                "assessed_status": assessment.get("assessed_status"),
                "strengths": assessment.get("strengths") or [],
                "warnings": assessment.get("warnings") or [],
                "recommendations": assessment.get("recommendations") or [],
                "message": event.get("message"),
                "action_required": event.get("action_required"),
            })

    inbox = []
    for name, rows in sorted(grouped.items(), key=lambda kv: len(kv[1]), reverse=True):
        latest = rows[0]
        action = classify(latest)

        inbox.append({
            "name": name,
            "count": len(rows),
            "latest_run_id": latest.get("run_id"),
            "first_seen_run_id": rows[-1].get("run_id"),
            "domain": latest.get("domain"),
            "score": latest.get("score"),
            "assessed_status": latest.get("assessed_status"),
            "activation": latest.get("activation"),
            "recommended_action": action,
            "human_decision_required": True,
            "missing_contract_parts": latest.get("warnings") or [],
            "recommendations": latest.get("recommendations") or [],
            "runs": [r.get("run_id") for r in rows[:12]],
            "policy": "system_proposes_human_governs_no_auto_stable",
        })

    summary: dict[str, Any] = {
        "total_groups": len(inbox),
        "total_raw_proposals": sum(item["count"] for item in inbox),
        "actions": {},
    }

    for item in inbox:
        action = item["recommended_action"]
        summary["actions"][action] = summary["actions"].get(action, 0) + 1

    payload = {
        "status": "ok",
        "mode": "primary_neuron_proposal_inbox",
        "summary": summary,
        "inbox": inbox,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.print:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print("\n=== PRIMARY PROPOSAL INBOX ===")
        for item in inbox[:25]:
            print(
                f'{item["count"]:03d} | {item["recommended_action"]} | '
                f'score={item["score"]} | domain={item["domain"]} | {item["name"]}'
            )
            if item["missing_contract_parts"]:
                print("   missing:", "; ".join(map(str, item["missing_contract_parts"][:4])))
        print(f"\nwritten: {out}")
    else:
        print(f"written: {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

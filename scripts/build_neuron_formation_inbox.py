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


def has_pipeline(candidate: dict[str, Any]) -> bool:
    return bool(candidate.get("creator_trainer_pipeline") and candidate.get("creator_spec") and candidate.get("training_review"))


def has_non_null_evidence(value: Any) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    return any(v not in (None, "", [], {}) for v in value.values())


def classify(name: str, items: list[dict[str, Any]]) -> str:
    lower = name.lower()
    latest = items[0]["candidate"]
    pipeline = has_pipeline(latest)
    evidence_ok = has_non_null_evidence(latest.get("evidence"))

    obsolete_android = any(x in lower for x in [
        "nodos-android",
        "hosts-llm-android",
        "llm-android-host",
        "deuda-federation",
    ])

    if obsolete_android and not pipeline:
        return "obsolete_legacy_android_debt"
    if len(items) >= 5 and not pipeline:
        return "merge_legacy_duplicates"
    if not evidence_ok:
        return "needs_better_evidence"
    if pipeline:
        return "ready_for_human_review"
    return "needs_creator_trainer_migration"


def main() -> int:
    parser = argparse.ArgumentParser(description="Construye bandeja agrupada de formación de neuronas candidatas.")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--out", default="triade/runs/neuron_formation_inbox.json")
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
        candidates = load_json(run_path / "background_neuron_candidates.json", [])
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            name = str(candidate.get("name") or candidate.get("display_name") or "unknown")
            grouped[name].append({
                "run_id": run_path.name,
                "candidate": candidate,
            })

    inbox = []
    for name, items in sorted(grouped.items(), key=lambda kv: len(kv[1]), reverse=True):
        latest = items[0]["candidate"]
        training = latest.get("training_review") or {}
        creator = latest.get("creator_spec") or {}

        inbox.append({
            "name": name,
            "display_name": latest.get("display_name") or name,
            "count": len(items),
            "latest_run_id": items[0]["run_id"],
            "first_seen_run_id": items[-1]["run_id"],
            "source": latest.get("source"),
            "severity": latest.get("severity"),
            "status": latest.get("status"),
            "pipeline": has_pipeline(latest),
            "training_status": training.get("status"),
            "training_score": training.get("score"),
            "required_human_review": training.get("required_human_review"),
            "evidence_non_null": has_non_null_evidence(latest.get("evidence")),
            "forbidden_actions_count": len(creator.get("forbidden_actions") or []) if isinstance(creator, dict) else 0,
            "success_metrics_count": len(creator.get("success_metrics") or []) if isinstance(creator, dict) else 0,
            "recommended_action": classify(name, items),
            "mission": latest.get("mission"),
            "latest_evidence": latest.get("evidence"),
            "runs": [item["run_id"] for item in items[:12]],
            "policy": "formation_inbox_grouped_no_auto_activation",
        })

    summary = {
        "total_groups": len(inbox),
        "total_raw_candidates": sum(item["count"] for item in inbox),
        "actions": {},
    }
    for item in inbox:
        action = item["recommended_action"]
        summary["actions"][action] = summary["actions"].get(action, 0) + 1

    payload = {
        "status": "ok",
        "mode": "neuron_formation_inbox",
        "summary": summary,
        "inbox": inbox,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.print:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print("\n=== TOP GROUPS ===")
        for item in inbox[:25]:
            print(
                f'{item["count"]:03d} | {item["recommended_action"]} | '
                f'pipeline={item["pipeline"]} | evidence={item["evidence_non_null"]} | {item["name"]}'
            )
        print(f"\nwritten: {out}")
    else:
        print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

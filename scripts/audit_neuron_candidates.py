from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def iter_run_dirs(runs_dir: Path, limit: int) -> list[Path]:
    return sorted(
        [p for p in runs_dir.glob("run-*") if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )[:limit]


def decisions_by_name(run_path: Path) -> dict[str, dict[str, Any]]:
    decisions = load_json(run_path / "neuron_candidate_decisions.json", [])
    if not isinstance(decisions, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for item in decisions:
        if isinstance(item, dict) and item.get("name"):
            out[str(item["name"])] = item
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita neuronas candidatas generadas por Tríade.")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--only-missing-pipeline", action="store_true")
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    rows: list[dict[str, Any]] = []

    for run_path in iter_run_dirs(runs_dir, args.limit):
        candidates = load_json(run_path / "background_neuron_candidates.json", [])
        decisions = decisions_by_name(run_path)

        if not isinstance(candidates, list):
            continue

        for item in candidates:
            if not isinstance(item, dict):
                continue

            name = str(item.get("name") or item.get("display_name") or "unknown")
            training = item.get("training_review") or item.get("training_result") or {}
            creator = item.get("creator_spec") or {}
            decision = decisions.get(name)

            row = {
                "run_id": run_path.name,
                "name": name,
                "display_name": item.get("display_name") or name,
                "status": item.get("status"),
                "source": item.get("source"),
                "severity": item.get("severity"),
                "activation": item.get("activation"),
                "pipeline": bool(item.get("creator_trainer_pipeline")),
                "created_by": item.get("created_by") or creator.get("created_by"),
                "formed_by": item.get("formed_by"),
                "training_status": training.get("status"),
                "training_score": training.get("score"),
                "required_human_review": training.get("required_human_review"),
                "policy": item.get("policy"),
                "decision": decision.get("decision") if isinstance(decision, dict) else None,
                "next_status": decision.get("next_status") if isinstance(decision, dict) else None,
                "mission": item.get("mission"),
                "evidence_non_null": has_non_null_evidence(item.get("evidence")),
                "forbidden_actions_count": len(creator.get("forbidden_actions") or []) if isinstance(creator, dict) else 0,
                "success_metrics_count": len(creator.get("success_metrics") or []) if isinstance(creator, dict) else 0,
            }

            if args.only_missing_pipeline and row["pipeline"]:
                continue

            rows.append(row)

    by_status = Counter(str(r.get("status")) for r in rows)
    by_training_status = Counter(str(r.get("training_status")) for r in rows)
    by_source = Counter(str(r.get("source")) for r in rows)
    by_name = Counter(str(r.get("name")) for r in rows)

    duplicates = {
        name: count
        for name, count in by_name.most_common()
        if count > 1
    }

    missing_pipeline = [r for r in rows if not r.get("pipeline")]
    missing_human_review = [r for r in rows if r.get("required_human_review") is not True]
    auto_stable = [
        r for r in rows
        if str(r.get("status")).lower() == "stable" or str(r.get("training_status")).lower() == "stable"
    ]
    weak_evidence = [r for r in rows if not r.get("evidence_non_null")]

    report = {
        "mode": "neuron_candidate_audit",
        "runs_scanned": args.limit,
        "total_candidates": len(rows),
        "by_status": dict(by_status),
        "by_training_status": dict(by_training_status),
        "by_source": dict(by_source),
        "duplicates": duplicates,
        "missing_pipeline_count": len(missing_pipeline),
        "missing_human_review_count": len(missing_human_review),
        "auto_stable_count": len(auto_stable),
        "weak_evidence_count": len(weak_evidence),
        "rows": rows,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not auto_stable else 2

    print("=== NEURON CANDIDATE AUDIT ===")
    print(json.dumps({
        "total_candidates": report["total_candidates"],
        "by_status": report["by_status"],
        "by_training_status": report["by_training_status"],
        "by_source": report["by_source"],
        "duplicates_count": len(duplicates),
        "missing_pipeline_count": len(missing_pipeline),
        "missing_human_review_count": len(missing_human_review),
        "auto_stable_count": len(auto_stable),
        "weak_evidence_count": len(weak_evidence),
    }, ensure_ascii=False, indent=2))

    print("\n=== TOP DUPLICATES ===")
    for name, count in list(duplicates.items())[:20]:
        print(f"{count:03d} | {name}")

    print("\n=== RECENT CANDIDATES ===")
    for r in rows[:40]:
        print(
            f'{r["run_id"]} | '
            f'{r["status"]}/{r["training_status"]} | '
            f'score={r["training_score"]} | '
            f'pipeline={r["pipeline"]} | '
            f'human={r["required_human_review"]} | '
            f'source={r["source"]} | '
            f'name={r["name"]}'
        )

    if auto_stable:
        print("\nERROR: Hay candidatas marcadas como stable automáticamente.")
        return 2

    return 0


def has_non_null_evidence(value: Any) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    for v in value.values():
        if v not in (None, "", [], {}):
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita neuronas primarias propuestas por el sistema.")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    run_dirs = sorted(
        [p for p in runs_dir.glob("run-*") if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )[: args.limit]

    rows = []
    for run_path in run_dirs:
        events = load_json(run_path / "system_events.json", [])
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, dict):
                continue
            if event.get("type") != "neuron_candidate_proposed":
                continue
            payload = event.get("payload") or {}
            assessment = payload.get("assessment") or {}
            warnings = assessment.get("warnings") or []
            recommendations = assessment.get("recommendations") or []

            rows.append({
                "run_id": run_path.name,
                "name": payload.get("name"),
                "neuron_id": payload.get("neuron_id"),
                "domain": payload.get("domain"),
                "registered_as": payload.get("registered_as"),
                "activation": payload.get("activation"),
                "score": assessment.get("score"),
                "assessed_status": assessment.get("assessed_status"),
                "warnings": warnings,
                "recommendations": recommendations,
                "action_required": event.get("action_required"),
                "message": event.get("message"),
            })

    by_name = Counter(str(r.get("name")) for r in rows)
    by_domain = Counter(str(r.get("domain")) for r in rows)
    repeated = {name: count for name, count in by_name.items() if count > 1}

    incomplete_contract = [
        r for r in rows
        if any(
            "Sin triggers" in str(w)
            or "Faltan entradas/salidas" in str(w)
            or "Sin métricas" in str(w)
            or "Sin evidencia" in str(w)
            for w in (r.get("warnings") or [])
        )
    ]

    report = {
        "mode": "primary_neuron_proposals_audit",
        "runs_scanned": args.limit,
        "total_proposals": len(rows),
        "by_domain": dict(by_domain),
        "repeated": repeated,
        "incomplete_contract_count": len(incomplete_contract),
        "rows": rows,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("=== PRIMARY NEURON PROPOSALS AUDIT ===")
    print(json.dumps({
        "total_proposals": report["total_proposals"],
        "by_domain": report["by_domain"],
        "repeated_count": len(repeated),
        "incomplete_contract_count": report["incomplete_contract_count"],
    }, ensure_ascii=False, indent=2))

    print("\n=== RECENT PRIMARY PROPOSALS ===")
    for r in rows[:30]:
        print(
            f'{r["run_id"]} | '
            f'name={r["name"]} | '
            f'domain={r["domain"]} | '
            f'score={r["score"]} | '
            f'status={r["assessed_status"]} | '
            f'action={r["action_required"]}'
        )
        if r.get("warnings"):
            print("  warnings:", "; ".join(map(str, r["warnings"][:4])))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audita uso de nodos edge Android en runs de Tríade.")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--only-edge", action="store_true")
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    run_paths = sorted([p for p in runs_dir.iterdir() if p.is_dir()], reverse=True)[: args.limit]

    rows = []
    nodes_seen = set()
    edge_used_count = 0
    edge_accepted_count = 0

    for run_path in run_paths:
        memory_diff = load_json(run_path / "memory_diff.json")
        edge_context = load_json(run_path / "edge_context.json")
        plan = load_json(run_path / "plan.json")

        edge_usage = memory_diff.get("edge_usage") or {}
        if not edge_usage and edge_context:
            edge_usage = {
                "used_edge": edge_context.get("used_edge"),
                "accepted": edge_context.get("accepted"),
                "node_id": edge_context.get("node_id"),
                "intent": (edge_context.get("intent_probe") or {}).get("intent"),
                "urgency": (edge_context.get("intent_probe") or {}).get("urgency"),
                "risk": (edge_context.get("intent_probe") or {}).get("risk"),
                "needs_tool": (edge_context.get("intent_probe") or {}).get("needs_tool"),
                "keywords": edge_context.get("keywords", []),
            }

        used_edge = bool(edge_usage.get("used_edge"))
        accepted = bool(edge_usage.get("accepted"))
        node_id = edge_usage.get("node_id") or ""

        if args.only_edge and not used_edge:
            continue

        if used_edge:
            edge_used_count += 1
        if accepted:
            edge_accepted_count += 1
        if node_id:
            nodes_seen.add(str(node_id))

        rows.append({
            "run_id": run_path.name,
            "used_edge": used_edge,
            "accepted": accepted,
            "node_id": node_id,
            "intent": edge_usage.get("intent") or "",
            "urgency": edge_usage.get("urgency") or "",
            "risk": edge_usage.get("risk") or "",
            "needs_tool": edge_usage.get("needs_tool"),
            "keywords": ", ".join(edge_usage.get("keywords", [])[:8]) if isinstance(edge_usage.get("keywords"), list) else "",
            "plan_has_edge": "edge_context" in plan,
        })

    print("=== EDGE USAGE SUMMARY ===")
    print(json.dumps({
        "runs_scanned": len(run_paths),
        "rows_reported": len(rows),
        "edge_used_count": edge_used_count,
        "edge_accepted_count": edge_accepted_count,
        "nodes_seen": sorted(nodes_seen),
    }, ensure_ascii=False, indent=2))

    print("\n=== EDGE USAGE ROWS ===")
    for row in rows:
        print(
            f'{row["run_id"]} | '
            f'used={row["used_edge"]} | '
            f'accepted={row["accepted"]} | '
            f'node={row["node_id"]} | '
            f'intent={row["intent"]} | '
            f'urgency={row["urgency"]} | '
            f'risk={row["risk"]} | '
            f'needs_tool={row["needs_tool"]} | '
            f'plan_edge={row["plan_has_edge"]} | '
            f'kw={row["keywords"]}'
        )


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json

from triade.core.stable_promotion_readiness import write_stable_readiness_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita si neuronas experimentales están listas para revisión stable.")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--out", default="triade/runs/stable_promotion_readiness.json")
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--min-activations", type=int, default=5)
    parser.add_argument("--min-diagnosis", type=int, default=5)
    parser.add_argument("--min-test-plan", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = write_stable_readiness_report(
        runs_dir=args.runs_dir,
        out_path=args.out,
        limit=args.limit,
        thresholds={
            "min_activations": args.min_activations,
            "min_diagnosis": args.min_diagnosis,
            "min_test_plan": args.min_test_plan,
        },
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("=== STABLE PROMOTION READINESS ===")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))

    for neuron in report["neurons"]:
        print(
            f'{neuron["name"]} | status={neuron["status"]} | '
            f'ready={neuron["ready_for_stable_review"]} | '
            f'activations={neuron["activation_count"]} | '
            f'diagnosis={neuron["diagnosis_count"]} | '
            f'test_plan={neuron["test_plan_count"]} | '
            f'last_run={neuron["last_run_id"]}'
        )
        if neuron["blockers"]:
            print("  blockers:", "; ".join(neuron["blockers"]))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

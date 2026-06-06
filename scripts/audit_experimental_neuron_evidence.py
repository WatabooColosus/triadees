from __future__ import annotations

import argparse
import json

from triade.core.experimental_neuron_evidence import write_experimental_evidence_ledger


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita evidencia acumulada de neuronas experimentales.")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--out", default="triade/runs/experimental_neuron_evidence.json")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    ledger = write_experimental_evidence_ledger(
        runs_dir=args.runs_dir,
        out_path=args.out,
        limit=args.limit,
    )

    if args.json:
        print(json.dumps(ledger, ensure_ascii=False, indent=2))
        return 0

    print("=== EXPERIMENTAL NEURON EVIDENCE ===")
    print(json.dumps(ledger["summary"], ensure_ascii=False, indent=2))

    for neuron in ledger["neurons"]:
        print(
            f'{neuron["name"]} | status={neuron["status"]} | '
            f'domain={neuron["domain"]} | activations={neuron["activation_count"]} | '
            f'diagnosis={neuron["diagnosis_count"]} | test_plan={neuron["test_plan_count"]} | '
            f'last_run={neuron["last_run_id"]}'
        )
        print("  stable_ready:", neuron["stable_promotion_ready"])
        print("  blockers:", "; ".join(neuron["promotion_blockers"]))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

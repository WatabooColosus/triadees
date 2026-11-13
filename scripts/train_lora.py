#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from triade.training import LoraTrainingConfig, RealLoraTrainer
from triade.training.governed_lora import default_base_model


def main() -> int:
    p = argparse.ArgumentParser(
        description="Entrenamiento LoRA real y gobernado de Tríade Ω"
    )
    p.add_argument("dataset")
    p.add_argument("--base-model", default=None)
    p.add_argument("--output", default="artifacts/adapters/triade-lora")
    p.add_argument("--max-steps", type=int, default=20)
    p.add_argument("--max-length", type=int, default=512)
    p.add_argument("--ood")
    p.add_argument("--forgetting")
    p.add_argument("--campaign-id")
    args = p.parse_args()
    cfg = LoraTrainingConfig(
        base_model=args.base_model or default_base_model(),
        output_dir=args.output,
        max_steps=args.max_steps,
        max_length=args.max_length,
    )
    result = RealLoraTrainer(cfg).train(
        args.dataset,
        ood_path=args.ood,
        forgetting_path=args.forgetting,
        campaign_id=args.campaign_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

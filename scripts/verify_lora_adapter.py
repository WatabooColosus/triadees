#!/usr/bin/env python3
"""Carga un adaptador PEFT guardado y ejecuta un canary sin activarlo en producción."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    parser = argparse.ArgumentParser()
    parser.add_argument("adapter")
    parser.add_argument(
        "--prompt",
        default="Instrucción: ¿Recuerdas después de cerrar una sesión?\nRespuesta:",
    )
    parser.add_argument("--max-new-tokens", type=int, default=48)
    args = parser.parse_args()
    adapter = Path(args.adapter).resolve()
    manifest = json.loads(
        (adapter / "triade_adapter_manifest.json").read_text(encoding="utf-8")
    )
    base = manifest["base_model"]
    tokenizer = AutoTokenizer.from_pretrained(adapter)
    model = AutoModelForCausalLM.from_pretrained(base, dtype=torch.bfloat16).to("cuda")
    model = PeftModel.from_pretrained(model, adapter, is_trainable=False)
    inputs = tokenizer(args.prompt, return_tensors="pt").to("cuda")
    with torch.no_grad():
        output = model.generate(
            **inputs, max_new_tokens=args.max_new_tokens, do_sample=False
        )
    text = tokenizer.decode(
        output[0][inputs.input_ids.shape[1] :], skip_special_tokens=True
    )
    print(
        json.dumps(
            {
                "loaded": True,
                "base_model": base,
                "adapter": str(adapter),
                "response": text,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

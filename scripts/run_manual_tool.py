#!/usr/bin/env python3
"""Lanzador explícito para diagnósticos manuales de Tríade.

No forma parte del worker continuo. Sólo ejecuta herramientas de diagnóstico
de una lista cerrada y exige ``--execute`` para pasar de inspección a ejecución.
Así los módulos manuales quedan descubribles sin convertirlos en trabajo de
fondo ni permitir comandos arbitrarios.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS: dict[str, str] = {
    "metacognition": "scripts/run_phase_07_metacognition.py",
    "memory_longitudinal": "scripts/run_phase_05_memory_longitudinal.py",
    "triadic_ablation": "scripts/run_phase_04_triadic_causality.py",
    "federation": "scripts/run_phase_14_federation.py",
    "autonomous_learning": "scripts/run_phase_09_autonomous_learning.py",
    "context_benchmark": "scripts/run_phase_1_learning_end_to_end.py",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="mostrar herramientas permitidas")
    parser.add_argument("--tool", choices=sorted(TOOLS), help="herramienta que se quiere ejecutar")
    parser.add_argument("--execute", action="store_true", help="ejecutar; sin esto sólo se valida")
    parser.add_argument("--timeout", type=int, default=900, help="tiempo máximo en segundos")
    args = parser.parse_args()

    if args.list or not args.tool:
        print(json.dumps({name: str(ROOT / path) for name, path in TOOLS.items()}, ensure_ascii=False, indent=2))
        return 0 if args.list else 2

    relative = TOOLS[args.tool]
    target = ROOT / relative
    if not target.is_file():
        print(json.dumps({"status": "error", "reason": "tool_missing", "tool": args.tool}), file=sys.stderr)
        return 2
    plan = {"status": "ready", "tool": args.tool, "script": relative, "execute_required": True}
    if not args.execute:
        print(json.dumps(plan, ensure_ascii=False))
        return 0

    result = subprocess.run(
        [sys.executable, str(target)],
        cwd=ROOT,
        timeout=max(1, args.timeout),
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from triade.core.edge_context import build_edge_context


def main() -> None:
    text = "Necesito conectar la APK como nodo real de procesamiento para Tríade."
    ctx = build_edge_context(text, enable_summary=True)
    print(json.dumps(ctx, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

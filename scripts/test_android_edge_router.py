from __future__ import annotations

import json
from triade.federation.edge_router import EdgeRouter


def main() -> None:
    router = EdgeRouter()

    print("=== SEMANTICA EDGE ===")
    print(json.dumps(router.semantic_summary(), ensure_ascii=False, indent=2))

    print("\n=== TASK: short_summary ===")
    result = router.run_lightweight_task(
        "short_summary",
        "Tríade es una arquitectura modular de inteligencia artificial con nodos federados y auditoría por run.",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

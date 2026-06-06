from __future__ import annotations

import json
from triade.core.edge_processing import EdgeProcessingService


def main() -> None:
    svc = EdgeProcessingService()

    sample = "Tríade es una arquitectura modular de inteligencia artificial con nodos federados y auditoría por run."

    print("=== SUMMARY ===")
    print(json.dumps(svc.summarize(sample).to_dict(), ensure_ascii=False, indent=2))

    print("\n=== KEYWORDS ===")
    print(json.dumps(svc.keywords(sample).to_dict(), ensure_ascii=False, indent=2))

    print("\n=== INTENT ===")
    print(json.dumps(svc.intent_probe("Necesito conectar la APK como nodo real de procesamiento.").to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

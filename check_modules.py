import json
from pathlib import Path

source = Path("artifacts/debt/debt-triage-latest.json")
if not source.is_file():
    print(f"debt_artifact_missing: {source}")
    raise SystemExit(2)

with source.open(encoding="utf-8") as f:
    data = json.load(f)

for entry in data["findings"]:
    if (
        entry["classification"] == "incomplete_subsystem"
        and entry["category"] == "modules_unreachable_from_entrypoint"
    ):
        print(f"{entry['table_or_status']}: {entry['evidence']}")

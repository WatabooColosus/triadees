import json
from pathlib import Path

source = Path("artifacts/debt/debt-triage-latest.json")
if not source.is_file():
    print(f"debt_artifact_missing: {source}")
    raise SystemExit(2)

with source.open(encoding="utf-8") as f:
    data = json.load(f)

for h in data["findings"]:
    if (
        h["classification"] == "incomplete_subsystem"
        and h["category"] == "tables_with_writer_and_no_rows"
    ):
        print(f"{h['table_or_status']}: {h['evidence']}")

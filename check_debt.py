import json

with open("artifacts/debt/debt-triage-latest.json") as f:
    data = json.load(f)

for h in data["findings"]:
    if (
        h["classification"] == "incomplete_subsystem"
        and h["category"] == "tables_with_writer_and_no_rows"
    ):
        print(f"{h['table_or_status']}: {h['evidence']}")

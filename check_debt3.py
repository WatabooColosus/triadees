import json
with open('artifacts/debt/debt-triage-latest.json') as f:
    data = json.load(f)

for entry in data['findings']:
    if entry['classification'] == 'incomplete_subsystem':
        print(f"{entry['category']}: {entry['table_or_status']} - {entry['evidence']}")
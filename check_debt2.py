import json
with open('artifacts/debt/debt-triage-latest.json') as f:
    data = json.load(f)

for entry in data['findings']:
    if entry['classification'] == 'incomplete_subsystem' and entry['category'] == 'tables_with_writer_and_no_rows':
        print(f"{entry['table_or_status']}: {entry['evidence']}")
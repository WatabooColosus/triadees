import json
with open('artifacts/debt/debt-triage-latest.json') as f:
    data = json.load(f)

# Original 10 tables from user message
original_10 = [
    'auth_api_keys', 'auth_audit', 'auth_email_identities', 
    'auth_rate_events', 'auth_sessions', 'auth_users',
    'autonomous_research_runs', 'constitution_violations',
    'federated_exchange_log', 'federated_nodes'
]

print("=== Original 10 tables ===")
for entry in data['findings']:
    if entry['table_or_status'] in original_10:
        print(f"{entry['table_or_status']}: {entry['classification']} - {entry['evidence'][:80]}...")

print("\n=== All contracted_by_design tables_with_writer_and_no_rows ===")
for entry in data['findings']:
    if entry['classification'] == 'contracted_by_design' and entry['category'] == 'tables_with_writer_and_no_rows':
        print(f"  {entry['table_or_status']}")

print("\n=== Summary ===")
by_cat = {}
for entry in data['findings']:
    cat = entry['classification']
    by_cat[cat] = by_cat.get(cat, 0) + 1
for k, v in sorted(by_cat.items()):
    print(f"  {k}: {v}")
import json
with open('artifacts/debt/debt-triage-latest.json') as f:
    data = json.load(f)

# Check the 10 tables user mentioned
tables = [
    'auth_api_keys', 'auth_audit', 'auth_email_identities', 
    'auth_rate_events', 'auth_sessions', 'auth_users',
    'autonomous_research_runs', 'constitution_violations',
    'federated_exchange_log', 'federated_nodes'
]

print("=== 10 tables from user message ===")
for entry in data['findings']:
    if entry['table_or_status'] in tables:
        print(f"{entry['table_or_status']}: {entry['classification']} - {entry['evidence'][:100]}")

print("\n=== All findings summary ===")
by_cat = {}
for entry in data['findings']:
    cat = entry['classification']
    by_cat[cat] = by_cat.get(cat, 0) + 1
for k, v in sorted(by_cat.items()):
    print(f"  {k}: {v}")

print(f"\nTotal: {len(data['findings'])}")
print(f"Graphs generated at: {data.get('graphs_generated_at', 'N/A')}")
print(f"Debt report generated at: {data.get('generated_at', 'N/A')}")
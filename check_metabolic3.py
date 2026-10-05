import sqlite3
import json

conn = sqlite3.connect('triade/memory/triade.db')
conn.row_factory = sqlite3.Row

print('=== metabolic_cycle recent ===')
rows = conn.execute('SELECT cycle_id, started_at, finished_at, status, mode, summary_json FROM metabolic_cycle ORDER BY cycle_id DESC LIMIT 5').fetchall()
for r in rows:
    print(dict(r))

print('\n=== autonomous_tasks running ===')
rows = conn.execute('SELECT task_id, task_type, status, created_at, updated_at FROM autonomous_tasks WHERE status IN ("running","leased")').fetchall()
for r in rows:
    print(dict(r))

print('\n=== learning_queue detail ===')
rows = conn.execute('SELECT id, status, candidate_id, created_at FROM learning_queue ORDER BY created_at DESC LIMIT 10').fetchall()
for r in rows:
    print(dict(r))

print('\n=== learning_evidence detail ===')
rows = conn.execute('SELECT id, decision, candidate_id, created_at FROM learning_evidence ORDER BY created_at DESC LIMIT 10').fetchall()
for r in rows:
    print(dict(r))

print('\n=== semantic_documents ===')
rows = conn.execute('SELECT id, status, domain, created_at FROM semantic_documents ORDER BY created_at DESC LIMIT 10').fetchall()
for r in rows:
    print(dict(r))

print('\n=== planning_graph ===')
rows = conn.execute('SELECT goal_id, status, parent_id, created_at FROM planning_graph ORDER BY created_at DESC LIMIT 10').fetchall()
for r in rows:
    print(dict(r))

print('\n=== workers ===')
with open('artifacts/internal_graphs/worker_graph.json') as f:
    wg = json.load(f)
for node in wg.get('nodes', []):
    if node.get('node_id', '').startswith('task_type:'):
        meta = node.get('metadata', {})
        print(f'{node["label"]}: state={node["state"]}, executions={meta.get("executions")}, recent={meta.get("recent_24h")}, ready={meta.get("ready_when_idle")}')

conn.close()
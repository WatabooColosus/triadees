import sqlite3
conn = sqlite3.connect('triade/memory/triade.db')
conn.row_factory = sqlite3.Row

print('=== SEMANTIC DOCUMENTS ===')
rows = conn.execute('SELECT id, status, domain, created_at FROM semantic_documents ORDER BY created_at DESC LIMIT 10').fetchall()
for r in rows:
    print('  {}: status={} domain={} | {}'.format(r['id'], r['status'], r['domain'], r['created_at']))

print('\n=== PLANNING GRAPH ===')
rows = conn.execute('SELECT goal_id, status, parent_id, created_at FROM planning_graph ORDER BY created_at DESC LIMIT 10').fetchall()
for r in rows:
    print('  {}: status={} parent={} | {}'.format(r['goal_id'], r['status'], r['parent_id'], r['created_at']))

print('\n=== AUTONOMOUS LEASE HEARTBEATS ===')
rows = conn.execute('SELECT * FROM autonomous_lease_heartbeats ORDER BY created_at DESC LIMIT 10').fetchall()
for r in rows:
    print(dict(r))

print('\n=== AUTONOMOUS TASKS STATUS COUNTS ===')
rows = conn.execute('SELECT status, COUNT(*) FROM autonomous_tasks GROUP BY 1 ORDER BY 2 DESC').fetchall()
for r in rows:
    print('  {}: {}'.format(r[0], r[1]))

print('\n=== METABOLIC RECEIPTS (lease_supervision) ===')
rows = conn.execute("SELECT need_id, status, started_at, finished_at FROM metabolic_receipts WHERE need_id LIKE 'lease_supervision%' ORDER BY started_at DESC LIMIT 10").fetchall()
for r in rows:
    print('  {}: {} | {} -> {}'.format(r['need_id'], r['status'], r['started_at'], r['finished_at']))

print('\n=== RUNTIME RECOVERY EVENTS ===')
rows = conn.execute('SELECT * FROM runtime_recovery_events ORDER BY created_at DESC LIMIT 10').fetchall()
for r in rows:
    print(dict(r))

print('\n=== WORKER EVENTS (last 20) ===')
rows = conn.execute('SELECT * FROM worker_events ORDER BY created_at DESC LIMIT 20').fetchall()
for r in rows:
    print('  {}: {} | {} | {}'.format(r['event_id'], r['event_type'], r['source'], r['created_at']))

print('\n=== BODEGA GLOBAL CONTEXT ===')
rows = conn.execute('SELECT * FROM bodega_global_context ORDER BY created_at DESC LIMIT 5').fetchall()
for r in rows:
    print(dict(r))

print('\n=== SEMANTIC DOCUMENTS COUNTS ===')
rows = conn.execute('SELECT status, COUNT(*) FROM semantic_documents GROUP BY 1').fetchall()
for r in rows:
    print('  {}: {}'.format(r[0], r[1]))

print('\n=== LEARNING QUEUE COUNTS ===')
rows = conn.execute('SELECT status, COUNT(*) FROM learning_queue GROUP BY 1').fetchall()
for r in rows:
    print('  {}: {}'.format(r[0], r[1]))

print('\n=== LEARNING EVIDENCE COUNTS ===')
rows = conn.execute('SELECT decision, COUNT(*) FROM learning_evidence GROUP BY 1').fetchall()
for r in rows:
    print('  {}: {}'.format(r[0], r[1]))

conn.close()
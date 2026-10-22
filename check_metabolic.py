import sqlite3

conn = sqlite3.connect('triade/memory/triade.db')
conn.row_factory = sqlite3.Row

# Metabolic cycles
print('=== metabolic_cycle ===')
c = conn.execute('SELECT COUNT(*) FROM metabolic_cycle').fetchone()[0]
print(f'Count: {c}')
if c > 0:
    rows = conn.execute('SELECT * FROM metabolic_cycle ORDER BY started_at DESC LIMIT 3').fetchall()
    for r in rows:
        print(f'  {dict(r)}')

# Lease recoveries
print('\n=== metabolic_receipts (lease_supervision) ===')
c = conn.execute('SELECT COUNT(*) FROM metabolic_receipts WHERE need_id LIKE "lease_supervision%"').fetchone()[0]
print(f'Count: {c}')
if c > 0:
    rows = conn.execute('SELECT need_id, status, evidence, created_at FROM metabolic_receipts WHERE need_id LIKE "lease_supervision%" ORDER BY created_at DESC LIMIT 5').fetchall()
    for r in rows:
        print(f'  {dict(r)}')

# Runtime recovery
print('\n=== runtime_recovery_events ===')
c = conn.execute('SELECT COUNT(*) FROM runtime_recovery_events WHERE state="runtime_recovered"').fetchone()[0]
print(f'Count: {c}')

# Autonomous tasks by status
print('\n=== autonomous_tasks status ===')
rows = conn.execute('SELECT status, COUNT(*) FROM autonomous_tasks GROUP BY 1 ORDER BY 2 DESC').fetchall()
for r in rows:
    print(f'  {r[0]}: {r[1]}')

# Stuck > 1h
print('\n=== stuck > 1h ===')
c = conn.execute("SELECT COUNT(*) FROM autonomous_tasks WHERE status IN ('pending','queued','leased','running','retry_wait','recovered') AND updated_at < datetime('now','-1 hour')").fetchone()[0]
print(f'Count: {c}')

# Dead letters
print('\n=== dead_letter ===')
c = conn.execute('SELECT COUNT(*) FROM autonomous_tasks WHERE status="dead_letter"').fetchone()[0]
print(f'Count: {c}')

# Learning
print('\n=== learning_queue ===')
rows = conn.execute('SELECT status, COUNT(*) FROM learning_queue GROUP BY 1').fetchall()
for r in rows:
    print(f'  {r[0]}: {r[1]}')

# Learning evidence
print('\n=== learning_evidence ===')
rows = conn.execute('SELECT decision, COUNT(*) FROM learning_evidence GROUP BY 1').fetchall()
for r in rows:
    print(f'  {r[0]}: {r[1]}')

# Semantic stable
print('\n=== semantic_documents stable ===')
c = conn.execute('SELECT COUNT(*) FROM semantic_documents WHERE status="stable"').fetchone()[0]
print(f'Count: {c}')

# Goals
print('\n=== planning_graph completed ===')
c = conn.execute('SELECT COUNT(*) FROM planning_graph WHERE parent_id IS NULL AND status="completed"').fetchone()[0]
print(f'Count: {c}')

# Causal uses
print('\n=== learning_queue causal_uses ===')
c = conn.execute('SELECT COALESCE(SUM(run_use_count),0) FROM learning_queue').fetchone()[0]
print(f'Total run_use_count: {c}')

# Metabolic cycles table
print('\n=== metabolic_cycle table exists? ===')
try:
    rows = conn.execute('SELECT COUNT(*) FROM metabolic_cycle').fetchone()[0]
    print(f'Count: {rows}')
except sqlite3.Error:
    print('Table does not exist')

conn.close()
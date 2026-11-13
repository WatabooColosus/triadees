import sqlite3

conn = sqlite3.connect("triade/memory/triade.db")
conn.row_factory = sqlite3.Row

rows = conn.execute(
    'SELECT task_id, task_type, status, created_at, updated_at, result_ref FROM autonomous_tasks WHERE task_type = "learning_evidence_generation" ORDER BY created_at DESC LIMIT 5'
).fetchall()
for r in rows:
    print("TASK:", dict(r))

conn.close()

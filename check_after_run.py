import sqlite3

conn = sqlite3.connect("triade/memory/triade.db")
conn.row_factory = sqlite3.Row

# Check the candidate status
rows = conn.execute(
    'SELECT id, status, candidate_id, updated_at FROM learning_queue WHERE candidate_id = "learn-ed45ed7cc2a54658"'
).fetchall()
for r in rows:
    print("QUEUE:", dict(r))

rows = conn.execute(
    'SELECT id, decision, candidate_id, created_at FROM learning_evidence WHERE candidate_id = "learn-ed45ed7cc2a54658"'
).fetchall()
for r in rows:
    print("EVIDENCE:", dict(r))

conn.close()

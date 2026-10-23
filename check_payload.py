import sqlite3

conn = sqlite3.connect("triade/memory/triade.db")
conn.row_factory = sqlite3.Row

rows = conn.execute(
    'SELECT payload_json FROM autonomous_tasks WHERE task_id = "task-2d704f8fdfd44090bf2aadf56904f97e"'
).fetchall()
for r in rows:
    print(r["payload_json"])

conn.close()

import json
import sqlite3

conn = sqlite3.connect('triade/memory/triade.db')
conn.row_factory = sqlite3.Row

rows = conn.execute('SELECT comparison_json FROM learning_evidence WHERE candidate_id = "learn-ed45ed7cc2a54658"').fetchall()
for r in rows:
    print(json.dumps(json.loads(r['comparison_json']), indent=2))
conn.close()
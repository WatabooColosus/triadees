import sqlite3
import json
conn = sqlite3.connect('triade/memory/triade.db')
conn.row_factory = sqlite3.Row

rows = conn.execute('SELECT * FROM learning_evidence WHERE candidate_id = "learn-ed45ed7cc2a54658"').fetchall()
for r in rows:
    d = dict(r)
    for k, v in d.items():
        if isinstance(v, str) and len(v) > 200:
            print(k, ':', v[:200], '...')
        else:
            print(k, ':', v)
    print()

conn.close()
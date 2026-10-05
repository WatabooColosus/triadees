import sqlite3
import json
conn = sqlite3.connect('triade/memory/triade.db')
conn.row_factory = sqlite3.Row

rows = conn.execute('SELECT baseline_evaluation_json, candidate_evaluation_json FROM learning_evidence WHERE candidate_id = "learn-ed45ed7cc2a54658"').fetchall()
for r in rows:
    print('BASELINE:')
    print(json.dumps(json.loads(r['baseline_evaluation_json']), indent=2))
    print()
    print('CANDIDATE:')
    print(json.dumps(json.loads(r['candidate_evaluation_json']), indent=2))
    print()
    print('COMPARISON:')
    print(json.dumps(json.loads(r['comparison_json']), indent=2))

conn.close()
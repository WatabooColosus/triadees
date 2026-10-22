import sqlite3

conn = sqlite3.connect('triade/memory/triade.db')
conn.row_factory = sqlite3.Row

# Check the candidate that just got evidence (learn-ed45ed7cc2a54658)
rows = conn.execute('SELECT * FROM learning_queue WHERE candidate_id = ?', ('learn-ed45ed7cc2a54658',)).fetchall()
for r in rows:
    print('QUEUE:', dict(r))

rows = conn.execute('SELECT * FROM learning_evidence WHERE candidate_id = ?', ('learn-ed45ed7cc2a54658',)).fetchall()
for r in rows:
    print('EVIDENCE:', dict(r))

rows = conn.execute('SELECT * FROM learning_evidence WHERE decision = "improved"').fetchall()
print('IMPROVED count:', len(rows))

rows = conn.execute('SELECT * FROM learning_evidence WHERE decision = "regressed"').fetchall()
print('REGRESSED count:', len(rows))

rows = conn.execute('SELECT * FROM learning_evidence WHERE decision = "unchanged"').fetchall()
print('UNCHANGED count:', len(rows))

rows = conn.execute('SELECT * FROM learning_evidence WHERE decision = "neutral"').fetchall()
print('NEUTRAL count:', len(rows))

# Check all evidence decisions
rows = conn.execute('SELECT decision, COUNT(*) FROM learning_evidence GROUP BY 1').fetchall()
for r in rows:
    print(f'  {r[0]}: {r[1]}')

conn.close()
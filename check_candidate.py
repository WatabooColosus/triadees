import sqlite3
conn = sqlite3.connect('triade/memory/triade.db')
conn.row_factory = sqlite3.Row

# Check the candidate content
rows = conn.execute('SELECT candidate_id, content, verification_notes, domain FROM learning_queue WHERE candidate_id IN ("learn-ed45ed7cc2a54658", "learn-6a3c98d3b9e24dd8", "learn-adcdf47ee8e94937")').fetchall()
for r in rows:
    print('CANDIDATE:', r['candidate_id'])
    print('  content:', r['content'][:200] if r['content'] else 'None')
    print('  domain:', r['domain'])
    print('  notes:', r['verification_notes'][:200] if r['verification_notes'] else 'None')
    print()

conn.close()
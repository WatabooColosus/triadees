import sqlite3
conn = sqlite3.connect('triade/memory/triade.db')
conn.row_factory = sqlite3.Row

print('=== METABOLIC CYCLES (last 10) ===')
rows = conn.execute('SELECT cycle_id, started_at, finished_at, status, mode, summary_json FROM metabolic_cycle ORDER BY cycle_id DESC LIMIT 10').fetchall()
for r in rows:
    print('  #{}: {} -> {} | {} | {} | {}'.format(r['cycle_id'], r['started_at'], r['finished_at'], r['status'], r['mode'], r['summary_json']))

print('\n=== LEARNING QUEUE (all) ===')
rows = conn.execute('SELECT id, status, candidate_id, created_at FROM learning_queue ORDER BY created_at DESC').fetchall()
for r in rows:
    print('  #{}: {} | {} | {}'.format(r['id'], r['status'], r['candidate_id'], r['created_at']))

print('\n=== LEARNING EVIDENCE (all) ===')
rows = conn.execute('SELECT id, decision, candidate_id, created_at FROM learning_evidence ORDER BY created_at DESC').fetchall()
for r in rows:
    print('  #{}: {} | {} | {}'.format(r['id'], r['decision'], r['candidate_id'], r['created_at']))

print('\n=== AUTONOMOUS TASKS (recent 20) ===')
rows = conn.execute('SELECT task_id, task_type, status, created_at, updated_at FROM autonomous_tasks ORDER BY created_at DESC LIMIT 20').fetchall()
for r in rows:
    print('  {}: {} | {} | created={} updated={}'.format(r['task_id'], r['task_type'], r['status'], r['created_at'], r['updated_at']))

print('\n=== QUALIA EXPERIENCES (last 10) ===')
rows = conn.execute('SELECT id, run_id, curiosity, confidence, risk, dominant_signal, created_at FROM qualia_experiences ORDER BY created_at DESC LIMIT 10').fetchall()
for r in rows:
    print('  {}: run={} cur={} conf={} risk={} sig={} | {}'.format(r['id'], r['run_id'], r['curiosity'], r['confidence'], r['risk'], r['dominant_signal'], r['created_at']))

print('\n=== QUALIA SIGNALS (last 10) ===')
rows = conn.execute('SELECT id, run_id, signal_type, intensity, valence, urgency, curiosity, created_at FROM qualia_signals ORDER BY created_at DESC LIMIT 10').fetchall()
for r in rows:
    print('  {}: {} | int={} val={} urg={} cur={} | {}'.format(r['id'], r['signal_type'], r['intensity'], r['valence'], r['urgency'], r['curiosity'], r['created_at']))

print('\n=== NEURON EDUCATION SESSIONS ===')
rows = conn.execute('SELECT id, neuron_id, status, baseline_score, post_score, result, created_at FROM neuron_education_sessions ORDER BY created_at DESC LIMIT 10').fetchall()
for r in rows:
    print('  {}: neuron={} status={} base={} post={} result={} | {}'.format(r['id'], r['neuron_id'], r['status'], r['baseline_score'], r['post_score'], r['result'], r['created_at']))

print('\n=== NEURON CERTIFICATIONS ===')
rows = conn.execute('SELECT * FROM neuron_certifications ORDER BY created_at DESC LIMIT 10').fetchall()
for r in rows:
    print(dict(r))

print('\n=== SEMANTIC DOCUMENTS ===')
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

conn.close()
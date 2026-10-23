import sqlite3

conn = sqlite3.connect("triade/memory/triade.db")
conn.row_factory = sqlite3.Row

print("=== LEARNING QUEUE STATUS ===")
rows = conn.execute(
    "SELECT status, COUNT(*) FROM learning_queue GROUP BY 1 ORDER BY 2 DESC"
).fetchall()
for r in rows:
    print(f"  {r[0]}: {r[1]}")

print()
print("=== RECENT CANDIDATES ===")
rows = conn.execute(
    "SELECT id, candidate_id, status, created_at FROM learning_queue ORDER BY created_at DESC LIMIT 10"
).fetchall()
for r in rows:
    print(
        "  #{}: {} | {} | {}".format(
            r["id"], r["candidate_id"], r["status"], r["created_at"]
        )
    )

print()
print("=== EVIDENCE DECISIONS ===")
rows = conn.execute(
    "SELECT decision, COUNT(*) FROM learning_evidence GROUP BY 1 ORDER BY 2 DESC"
).fetchall()
for r in rows:
    print(f"  {r[0]}: {r[1]}")

print()
print("=== METABOLIC CYCLES (last 5) ===")
rows = conn.execute(
    "SELECT cycle_id, started_at, status, mode FROM metabolic_cycle ORDER BY cycle_id DESC LIMIT 5"
).fetchall()
for r in rows:
    print(
        "  #{}: {} | {} | {}".format(
            r["cycle_id"], r["started_at"], r["status"], r["mode"]
        )
    )

print()
print("=== QUALIA (recent) ===")
rows = conn.execute(
    "SELECT id, run_id, neuron_type, confidence, risk, source, created_at FROM qualia_experiences ORDER BY created_at DESC LIMIT 5"
).fetchall()
for r in rows:
    print(
        "  {}: type={} conf={} risk={} source={} | {}".format(
            r["id"],
            r["neuron_type"],
            r["confidence"],
            r["risk"],
            r["source"],
            r["created_at"],
        )
    )

conn.close()

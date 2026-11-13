import sqlite3

conn = sqlite3.connect("triade/memory/triade.db")
conn.row_factory = sqlite3.Row

rows = conn.execute(
    'SELECT * FROM learning_evidence WHERE candidate_id = "learn-ed45ed7cc2a54658"'
).fetchall()
for r in rows:
    print("EVIDENCE ID:", r["id"])
    print("Candidate:", r["candidate_id"])
    print("Decision:", r["decision"])
    print("Control runs:", r["control_run_ids"])
    print("Treatment runs:", r["treatment_run_ids"])
    print("Artifact ref:", r["artifact_ref"])
    print(
        "Baseline eval:",
        r["baseline_evaluation_json"][:200]
        if r["baseline_evaluation_json"]
        else "None",
    )
    print(
        "Candidate eval:",
        r["candidate_evaluation_json"][:200]
        if r["candidate_evaluation_json"]
        else "None",
    )
    print("Comparison:", r["comparison_json"][:200] if r["comparison_json"] else "None")
    print()

conn.close()

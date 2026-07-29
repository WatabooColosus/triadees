# Runtime concurrency report

- Date: 2026-07-29 UTC
- Branch: `codex/runtime-truth-stabilization`
- Command: `python scripts/run_runtime_concurrency_test.py --output-dir runs/concurrency-validation-phase17 --tasks 100 --workers 3`
- Execution type: real local multiprocessing with SQLite; not simulated.

## Observed result

```json
{
  "task_rows": 101,
  "enqueue_calls": 111,
  "workers": 3,
  "statuses": {
    "completed": 90,
    "dead_letter": 11
  },
  "effects": 90,
  "duplicate_effects": 0,
  "recovered_leases": 1,
  "missing_artifacts": 0,
  "db_integrity": "ok",
  "all_accounted": true,
  "elapsed_seconds": 1.705122
}
```

The test made 111 enqueue calls: 100 distinct tasks, 10 repeated idempotency
keys, and one task whose first lease was assigned to a deliberately abandoned
worker. Recovery reclaimed that expired lease before three worker processes
contended on the database.

Eleven injected failure/timeout tasks exhausted their single allowed attempt
and reached `dead_letter`. The remaining 90 tasks published one effect and one
existing result artifact each. SQLite `PRAGMA integrity_check` returned `ok`.

## Reproduction evidence

Runtime evidence is under `runs/concurrency-validation-phase17/` and is not
committed. Re-running the command creates a fresh database only when the target
directory is new; select a new output directory for an independent run.

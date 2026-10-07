# TRIADE OMEGA - closure evidence

Verified source: `a838ee2400e19a05a1d6aa1a2b0b6ca7f1f180db`. Initial source: `7a2a73b`. Delivery adds only these reports.

| Gate | Result / scope |
|---|---|
| Tests | 2697 collected, 2697 passed, 0 failed, 0 skipped |
| Frontend | PASS, unchanged measured source and bundles |
| Runtime E2E / SQLite / concurrency | PASS / PASS / PASS |
| Learning | FAIL: 0/3 before, 0/3 learned, 0/3 control; Measurement Core neutral |
| Recovery | Actual isolated in-flight task: 2.17s, zero duplicated effects; actual API: 59.66s, same supervisor, different PID |
| Clean restart | True, actual isolated ASGI, workers stopped, locks released, nonempty identity preserved; consolidated learned-state persistence unproved |
| Soak | 1806.78s stopwatch, 56 metabolic cycles, 138 completed tasks, 0 human inputs, 0 internal errors |
| RSS | 104.31 to 102.29 MiB, peak 105.28, STABLE for this window |
| Resources | Observed FULL / LIGHT / FULL; machine-level, restart between first two observations |
| Security | PARTIAL, minimum phase review and secret scan; no new public endpoints or permissions |
| CI | RED-EXTERNAL, billing/spending limit, jobs did not start |
| Rollback / 24h / 72h | NOT_YET_PROVEN |

Score: **5.3/10 certification coverage**, not intelligence. Thresholds were not lowered to award 8; the external CI exception only follows the operator's explicit policy. **LEVEL_8_CANDIDATE: False.**

The soak stopwatch includes the probes; first-to-last sample stamps span 1799.80s. The recorded start-to-last timestamp exceeds 1800s. No rounding or invented uptime is used. RAM-free, temperature and Ollama residency were not recorded throughout this window; do not call it full hardware certification. Learning events did not increase.

Reproduce (repository root):

```
python -m scripts.run_level8_learning_transfer
python -m scripts.run_level8_task_recovery
python -m scripts.run_level8_clean_restart
python -m scripts.run_level8_soak --seconds 1800 --interval 60
python -m scripts.run_level8_api_recovery
python scripts/level8_audit.py
```

API recovery deliberately terminates the verified Triaude API; use only for an authorized fault test. The in-flight task and API restart are separate environments, not a single production-task experiment. For future 24h/72h observation use `--seconds 86400` / `--seconds 259200`; completion alone is not certification.

The unsuccessful earlier learning trials and initial invalid clean-stop measurement are preserved. JSON-schema output is identical in all learning arms and supplies no expected values ([Ollama API](https://docs.ollama.com/api/generate)). SQLite constraints, not model self-reports, score the actual effects. No production rows were fabricated for health or learning.

Exact artifacts and remaining gates: [FINAL_AUDIT.json](FINAL_AUDIT.json), [final_score.json](final_score.json). Logical source diff: `git diff 7a2a73b a838ee2400e19a05a1d6aa1a2b0b6ca7f1f180db`. Test commands/hashes: [test_evidence.json](test_evidence.json).

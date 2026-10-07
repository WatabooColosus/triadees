# Local baseline — 2026-10-07 UTC

Revision: `ee857992ea9e753c2dea23f8ca2c8f2d45a85730`, main, equal to fetched origin/main before edits.

Reproduce: `python scripts/capture_level8_baseline.py`. Exact observations and timestamps: `baseline.json`, `runtime_followup.json`, `background_autonomy.json`, `resource_profile.json`.

| Capability | Classification | Observable evidence / limit |
|---|---|---|
| SQLite integrity | REAL | integrity_check=ok; WAL; 112 tables; zero foreign-key violations |
| API liveness / deep health | REAL at observation | Four endpoints responded; HTTP 200 alone is not E2E proof |
| Workers / metabolism | PARCIAL | Workers active; metabolism 98 to 113 cycles; full result-learning chain pending |
| Scheduler | NO DEMOSTRADA | heartbeat scheduler_active absent; not inferred from worker status |
| Independent learning | NO DEMOSTRADA | historical verified statuses not sufficient provenance certification |
| Causal production learning | NO DEMOSTRADA | prior usage counter and answer-in-prompt cannot establish causality |
| Education | PARCIAL | focused tests pass; runtime before/after chain remains pending |
| Metacognition | PARCIAL | existing engine tested; post-hoc predictions removed; historical calibration not certified |
| Recovery / restart | NO DEMOSTRADA in production | isolated lease contention proof; clean productive restart persistence pending |
| Resources | PARCIAL | actual Windows API RSS/CPU sample; peak and low-RAM transitions unproven |
| Federation / Android | NO DEMOSTRADA | two-node complete receipt chain not certified |
| Security | PARCIAL | Windows backup ACL tests executed; whole-system security audit incomplete |
| Frontend | REAL build | npm ci and npm build exit 0; no lint/typecheck/test scripts defined |
| Hosted CI | BLOCKED externally | billing/spending limit prevents jobs from starting |
| Longitudinal autonomy | NO DEMOSTRADA | no 24h/72h claim; collector available, certification pending |

Priority blockers: (1) external CI runner billing, (2) complete local suite, (3) contaminated educational/causal measurements, (4) production recovery/restart chain, (5) low-resource and longitudinal certification. Existing pre-existing operational databases and heap dump are preserved, excluded from staging.

Current baseline.json was recaptured read-only at source `c6fd27544e2ebecf3e4e9ea2f94b646f2c97d32d` after recovery; the table above records initial classifications, not a new certification. Final results and remaining limits: FINAL_AUDIT.md.

# Final local audit

Initial SHA: `ee857992ea9e753c2dea23f8ca2c8f2d45a85730`. Verified source SHA: `c6fd27544e2ebecf3e4e9ea2f94b646f2c97d32d`. The later evidence-only commit does not alter tested source; obtain delivery SHA with `git rev-parse HEAD`.

## Verified results

- Full suite: **2686 collected / 2686 passed / 0 failed / 0 skipped**, exit 0, 847.25 seconds. Command: `TRIADE_REAL_E2E=1 TRIADE_FULL_CERT=1 python scripts/run_level8_tests.py` (environment variables set through subprocess on Windows). Exact command/hash/JUnit: [test_evidence.json](test_evidence.json), [full_suite.xml](full_suite.xml).
- Frontend: `npm ci --prefix frontend` and `npm run build --prefix frontend`, exit 0, hashed 256982-byte output. No lint/typecheck/test scripts are defined. [frontend_evidence.json](frontend_evidence.json).
- Real HTTP/Ollama/runtime E2E: five tests passed. This verifies transport, Central response, persistence and active components, not autonomous learning causality. [real_e2e.xml](real_e2e.xml).
- SQLite: read-only `integrity_check=ok`, WAL, 112 tables, zero foreign-key violations. [baseline.json](baseline.json).
- Two-worker isolated concurrency: 28 effects, zero duplicates, one recovered lease, consistent database. [concurrency.json](concurrency.json).
- Actual API crash: PID 22244 exited, existing PowerShell supervisor PID 23492 started API PID 3936 without manual start. Subsequent metabolism cycles increased 2 to 3 with no tick error. Task Scheduler restart is **not** credited for this recovery. [automatic_recovery_observed.json](automatic_recovery_observed.json), [automatic_recovery_followup.json](automatic_recovery_followup.json).
- Approved Windows task settings applied with prior XML backup: 3 retries, 1-minute interval, no 72-hour timeout, battery allowed. [windows_recovery_applied.json](windows_recovery_applied.json). No host changes beyond the explicitly approved scope.
- Hosted CI: **RED-EXTERNAL**. Five jobs had no steps and GitHub reported account billing/spending limit failure. [ci_blocker.json](ci_blocker.json), [ci_annotations.json](ci_annotations.json). Those runs belong to the initial SHA; new-SHA runner execution is not certified.

## Repairs

Windows long-path receipts and real handler artifacts; reused research status mapping; bounded architectural scanning and linear graph deduplication; missing UI debt fields; private Windows backup ACL enforcement; isolated test keys; Qwen 1.5B adapter family mapping; Windows tests and file locks; truthful read-only audit handling. Educational answers were removed from task input, post-lesson observations no longer pretend to be baselines, and observed outcomes no longer manufacture earlier predictions. The production DB was not manually populated to pass gates.

The exact source diff is `git diff ee857992ea9e753c2dea23f8ca2c8f2d45a85730 c6fd27544e2ebecf3e4e9ea2f94b646f2c97d32d`. Logical commits are listed in [FINAL_AUDIT.json](FINAL_AUDIT.json).

## Pending proof and limits

- GitHub billing/spending limit prevents hosted jobs from starting; branch protection inspection HTTP 403
- No paired target-hidden independent BEFORE/AFTER demonstrating beneficial education and causal production use; stable semantic documents observed: 0
- Metabolism currently light_background at about 1.42 GB free RAM; nourishment and stable consolidation denied while minimal workers and heartbeat remain active
- Clean productive restart, in-flight task recovery, production rollback and runtime calibration remain unproved
- Two-node federation and 24h/72h runtime evidence remain unproved
- Scoring CLI imports only revision-bound test/frontend/DB evidence; other protocol adapters are incomplete, so its 1.2 coverage score is not a cognitive rating
- Longitudinal collector emits COMPLETED, while autonomy gate requires CERTIFIED; collector completion cannot pass that gate until protocol integration is implemented

Autonomy snapshot: 5 PASS, 15 PENDING, 0 BLOCKED. Zero BLOCKED does not mean all capabilities work. [autonomy_current.json](autonomy_current.json).

Restart preserved existing identity, routes, predictions and verified knowledge; stable memory was empty before and after, so that proves no stable-learning persistence. [restart_continuity.json](restart_continuity.json). Learning has 4 verified candidates and 4 registered uses, but no certified independent beneficial before/after: [learning_longitudinal.json](learning_longitudinal.json).

Resource snapshot is not peak-RAM/8GB certification. Current heartbeat says full_local_guarded but metabolism's effective governor says light_background: the more restrictive actual component controls its nourishment. Do not present that as full functioning. [resource_profile.json](resource_profile.json), [automatic_recovery_observed.json](automatic_recovery_observed.json).

Long-run command prepared: `python scripts/run_long_validation.py --hours 24 --interval 1 --label level8-24h` (then 72 hours). It collects observations; completion alone is not certification. No 24-hour or 72-hour success claimed.

## Level

Previous 6.8/10: approximate supplied reference, not independently measured. Calculated **1.2/10 is certification coverage**, limited by incomplete evidence adapters; it is not a rating of intelligence. Each accepted PASS contributes the documented dimension fraction in `scripts/level8_audit.py`; pending gates earn zero. [final_score.json](final_score.json).

**LEVEL_8_CANDIDATE = FALSE.** No consciousness, AGI or singularity claim.

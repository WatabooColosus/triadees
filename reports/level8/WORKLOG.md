# Local level-8 verification worklog

Initial revision: `ee857992ea9e753c2dea23f8ca2c8f2d45a85730`, branch `main`, equal to freshly fetched `origin/main` on 2026-10-07 UTC. This work does not certify level 8.

## A — Baseline

HECHO: inspected Git, workflows, package scripts, tests, production SQLite and live endpoints. Added a reproducible read-only collector.

EVIDENCIA: `baseline.json`; `python scripts/capture_level8_baseline.py`. SQLite integrity `ok`, WAL, 112 tables, zero foreign-key violations. API health, deep health, heartbeat and metabolism returned HTTP 200. These are snapshots, not complete circuit certification.

FALTA: component-by-component usage chains and complete classification of legacy/dead code.

RIESGO: historical counts cannot prove current activity. Production database and pre-existing untracked runtime artifacts are preserved.

SIGUIENTE PASO: two observations of natural progress and the full local suite.

## B — CI and local validation

HECHO: authenticated read-only GitHub run/job/check annotation inspection. Reproducible frontend installation/build succeeded. Full local pytest attempted; first attempt interrupted explicitly after diagnosing excessive structural scanning and Windows long paths. Restarted with `scripts/run_level8_tests.py` and JUnit evidence.

EVIDENCIA: `ci_blocker.json`, `ci_annotations.json`, `ci_job_evidence.json`, `frontend_evidence.json`, `initial_suite_interruption.json`. Five named CI workflows have zero executed steps. GitHub annotation explicitly reports billing/spending-limit failure. Branch protection inspection returned HTTP 403.

FALTA: external account billing resolution and fresh GitHub execution; full local suite completion/revalidation after repairs.

RIESGO: CI is RED-EXTERNAL; no repository patch can restore available hosted runner quota. Local failures remain separate from this external failure.

SIGUIENTE PASO: complete local JUnit results, classify every failure and skip.

## Repairs supported by direct failures

- Windows artifact paths: temporary filenames exceeded the Windows legacy path limit; concurrent task exceptions were silently ignored. Extended-path IO now preserves evidence and errors are reported. Timeout/retry regression and long-path tests passed.
- Structural atlas: bundled `tools/python` interpreter was scanned as Tríade architecture. Only that infrastructure subtree is excluded; operator tools remain visible. Regression test passed.
- Documentation: one CP1252 byte in otherwise UTF-8 `docs/STATUS_CURRENT.md` blocked five documentation tests. Repaired that exact byte; six documentation tests passed.
- Activation contracts: `kg_edges`, `kg_contradictions` and `goal_dependencies` contained 1, 1 and 6 rows. ON_DEMAND relations cannot promise perpetual emptiness. Producer/reader/proof requirements remain.
- LoRA contract tests: fixture expected a 3B model but borrowed the operator's current 1.5B configuration. Added isolated compatible YAML; four tests passed without removing governance gates.
- Education: removed post-lesson runs being repurposed as pre-lesson baselines. Missing baselines remain missing; measured applications remain observable. Fifty focused learning/education/metacognition tests passed.
- Education exercise no longer places the expected learned answer in user input. Retrieval remains a proxy until a controlled comparison proves causality.
- Metacognition: no longer manufactures a prediction from an already observed outcome. Existing historical predictions are untouched and not certified as calibrated evidence.
- Backup security: Windows ACL verification replaces the prior permission-check bypass; files are protected and checked. Tests use real platform permissions. Test-scope resolution no longer falls back to operator key-location files.
- Portable process and launcher tests: use process status rather than Windows `os.kill(pid, 0)` and platform-aware absolute paths.

## C — Autonomy truth gate

HECHO: made audit SQLite connections read-only; removed automatic PASS from usage counters, canary registrations, dead letters, federation registry entries and mere resource mode selection. Scheduler is not inferred from worker activity. Collector COMPLETED does not certify a longitudinal window.

EVIDENCIA: `scripts/audit_autonomy_gates.py`, `tests/test_autonomy_audit_truth.py`; two tests passed. `scripts/level8_audit.py` derives certification coverage from gates and enforces critical caps; seven tests passed.

FALTA: causal learning, production education chain, measured recovery/rollback, restart, low-resource transitions, federation and significant longitudinal evidence.

RIESGO: previously reported PASS counts overestimated proof. Missing proof now remains PENDING, even if implementation exists.

SIGUIENTE PASO: repair remaining local failures before certification. Do not claim 8.0.

## Final verification and explicit pending phases

HECHO: completed full Windows suite (2686 passed, zero failed/skipped), frontend rebuild, five real E2E tests, SQLite audit, isolated concurrency and actual API crash recovery through the existing supervisor. Approved Task Scheduler recovery settings applied; task-based ownership not certified.

EVIDENCIA: FINAL_AUDIT.json/md and linked revision-bound artifacts. Source c6fd275 was unchanged during the final full suite.

FALTA: causal learning, independent educational before/after, clean production restart/recovery/rollback, runtime calibration, physical low-resource transitions, longitudinal certification and federation. Scoring adapters and collector/certifier contracts remain incomplete.

RIESGO: actual metabolism light_background prevents nourishment below its RAM threshold despite heartbeat full_local_guarded. Neither historical counters nor successful test fixtures establish production improvement. Hosted CI blocked by billing.

SIGUIENTE PASO: preserve evidence, push authorized commits; next engineering priority is align effective governors and implement independently scored educational baseline/control/use protocol, before federation. Do not claim level 8.

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

## Final closure phase

HECHO: real procedural transfer trial and negative control, physical in-flight worker termination and idempotent recovery, actual API supervisor recovery, clean sandbox lifespan restart, measured 30-minute maintenance soak, focused and complete validation.

EVIDENCIA: FINAL_AUDIT.json/md, source a838ee2400e19a05a1d6aa1a2b0b6ca7f1f180db, linked measured artifacts.

FALTA: beneficial learning (0/3), productive education/use, consolidated learned-state restart, rollback and 24h/72h proof.

RIESGO: maintenance continuity is not cognitive-learning autonomy; isolated task recovery is not one production-task fault test; historical resource observations span restart.

SIGUIENTE PASO: repair actual knowledge application, preserving neutral Measurement Core outcome and safety gates. No level 8 declaration.


## Rectificacion de bloqueos - 2026-10-07T03:03Z
HECHO: gates completos separados de mantenimiento y recuperacion aislada; BLOCKERS.md ordenado.
EVIDENCIA: health/deep healthy, PID 11212, heartbeat 435->438; 10 tests focalizados aprobados; audit 4.5/10 de cobertura, candidato false.
FALTA: transferencia causal, uso productivo, recuperacion correlacionada, autonomia cognitiva, persistencia y rollback.
RIESGO: confundir pruebas aisladas con circuitos productivos completos. Suite completa anterior no repetida.
SIGUIENTE PASO: diagnosticar consumidor y contexto efectivo. Sin reinicios ni cambios en DB.


## Evolution learning closure - 2026-10-07
HECHO: bounded arithmetic tool, structured model transport, normal equation probes, real source schema validation at promotion/injection, and token limits.
EVIDENCIA: frozen source 9eb6962; transfer baseline 1/6, learned 6/6, negative 1/6; real leased WorkerLoop control 0/5, treatment 5/5, evidence_verified and completed. Final suite 2716 passed, 0 failed, 0 skipped. SQLite integrity ok, WAL, FK violations 0.
FALTA: full neuronal education/use chain (no_compatible_neuron), productive recovery, cognitive autonomy, learned restart, rollback, permanent supervisor/regression shield/dashboard. Task remains incomplete; no level 8 claim.
RIESGO: coverage 2.4/10 is current-source certification coverage, not capability. Old operational/resource windows remain historical. Latest API healthy with live workers; resource mode light_background. Failed and development suite attempts are preserved.
SIGUIENTE PASO: legitimate neuronal need/domain formation and correlated education/use before later phases. No new daemon or automatic source modification activated.

## Productive closure ? source 8fdfe9c8a031365f4a80e73ddf9de25273646172

HECHO: explicit domains are preserved and validated; Creadora receives real IO/evidence contracts; normal distribution workers persist governed admission proposals without activating neurons. Windows learning receipts use the existing atomic writer; staging names avoid repeated task IDs.
EVIDENCIA: domain_admission_tests / staging_review_tests; normal leased admission task in productive_learning_chain_v2.json; actual long-path failure versus atomic write in windows_learning_receipt_io.json. Full-suite failed attempts remain archived; final suite is running on frozen source.
FALTA: executable held-out curriculum, evidence-to-neuron activation bridge, correlated productive application/consolidation/reuse, productive crash recovery, persistence and cognitive autonomy; evolution supervisor not implemented.
RIESGO: live API has not reloaded this source; RAM/resource restrictions remain active. First pytest invocation incorrectly escaped a temporary path outside the repository; that directory was left untouched. A stopped intermediate test harness is marked ABORTED_NOT_CERTIFIED, not passed.
SIGUIENTE PASO: finish current source validation, publish exact evidence and continue legitimate held-out formation.

HECHO FINAL: suite 2728/2728 PASS, frontend PASS, SQLite ok; source 8fdfe9c8a031365f4a80e73ddf9de25273646172.
EVIDENCIA: test_evidence.json and PRODUCTIVE_CLOSURE.md.
FALTA: neuronal certification and productive chain; no Level 8 declared.
RIESGO: unreloaded live API and incomplete downstream gates.
SIGUIENTE PASO: executable governed held-out formation.

## Rectification - 2026-10-08T00:47:38.359862+00:00
HECHO: corrected overstatement about complete IO contracts in the reused runtime admission; no source or production data changed.
EVIDENCIA: rectification_observation_before/after.json; unchanged tested source and matching JUnit hash; metabolic counter advanced without injected tasks; heartbeat timestamp advanced but counter decreased from 6811 to 1 with unchanged PID (undiagnosed anomaly).
FALTA: complete correlated admission, held-out formation/certification, productive learning and downstream gates.
RIESGO: permissions and heartbeat progress do not demonstrate learning; current source is not certified as reloaded in the API. CI remains a timestamped external-blocker observation.
SIGUIENTE PASO: connect legitimate formation and certification while preserving original evidence.

## Internal graph navigation ? 2026-10-08
HECHO: reused existing layer/organ/worker/table/neural/vital graphs; corrected false handoff verification based only on endpoint recency. API reloaded source 621e2f2 with a process-scoped single-model/single-inference Ollama profile.
EVIDENCIA: internal_graph_navigation.json/md; provider_profile_and_reload.json; heartbeat progressed 7749?7760 with PID21200; real frontend/API/Central/Ollama focused test PASS.
FALTA: graph-focused suite finished 62 PASS; current complete suite remains 2741 PASS / 1 FAIL on 4b8684e, with the literal-output failure repaired and only focused runtime retest proven. No full-suite PASS for current source claimed. Executable held-out training, certification, activation, consolidation and productive recovery remain unproven.
RIESGO: graph connectivity/imports do not prove causal transfers. The provider profile is session-only and is not persisted across Windows reboot.
SIGUIENTE PASO: finish graph tests, reload final source and recertify before release; continue the missing training/certification bridge without manual activation.

RECARGA: source 037b58e verified at bootstrap; the normal restart health check timed out before the previous worker lease expired. The API remained available; passive lease recovery observation is preserved separately in graph_navigation_reload.json. The live vital graph returned ten handoff_verified=false edges. No release/full-suite certification or push claimed.

RESULTADO RECARGA: normal lease recovery completed without queue/lease edits; health healthy, workers active, PID11924, effective full_local_guarded, heartbeat7806 at 2026-10-08T02:24:09Z. Evidence: reports/evolution/graph_navigation_reload.json. Remaining causal formation/education/consolidation gates unchanged.

## Sequential learning closure ? 2026-10-08
HECHO: saved eight sequential phases with explicit exit gates; investigated phase 1 using existing graph links, actual planner/formation/trainer/evaluation code, and read-only existing experiment DB.
EVIDENCIA: reports/evolution/learning_closure_phases.json/md; candidate neuron1 remains candidate, training rows0. DomainAdmissionCoordinator.form emits pending_executable_curriculum; structural training score is not competence.
FALTA: phase2 executable curriculum and normal-worker execution, followed by independent certification and registry/router bridge.
RIESGO: NeuronRegistry.store_training changes neuron status; it must not be used with a structural review score to fabricate competence. Stable education policy currently declares HUMAN_REQUIRED and must be resolved through governance, not bypassed.
SIGUIENTE PASO: phase2 curriculum/execution contract, focal tests and normal-worker evidence before phase3 certification.

## Sequential execution 2026-10-08

HECHO: governed training 2/2; held-out treatment 5/5 vs both controls 0/5; certified neuron activation; five measured education applications; earned-trust consolidation; two independent runtime processes reuse the stable knowledge; real WorkerLoop crash recovery; measured regression rollback.

EVIDENCIA: reports/evolution/admission_*_latest.json. Recovery 61.625 seconds, lost_tasks=0, duplicate_effects=0. Stable ID sem-b9d00d6f2a9c4544. Existing experiment DB only; runtime handlers and governors are normal production code. API clean restart PID 11924 -> 9284, source 794bee09c089dfe31286f799d54e85b9b0ddcf2f, identity preserved.

FALTA: same-revision final suite, production cognitive autonomy with measured learned benefit, deployed supervisor in-flight recovery, continuous evolution supervisor. Source revisions for earlier stage executions differ; do not mark complete certification.

RIESGO: certification traffic overlaps the current operational soak; no-chat autonomy cannot be inferred from this window. No historical evidence overwritten as a current PASS.

SIGUIENTE PASO: finish final tests and operational observation, correlate real background tasks; retain pending gates honestly.

## Automatic closure corrections and observation 2026-10-08T04:43:22.570398+00:00

HECHO: fixed SQLite BUSY escaping event scheduler; isolated each full-suite JUnit; shared admission transition policy in scheduler and worker; initialized research/education storage through owning migrations; serialized model tasks across lanes; bounded infrastructure-only certification retries to 3; prioritized finishing trained admissions over new candidate creation.

EVIDENCIA: source a4fdde65251d35791402bb6ded7c60cd5de97d3a. scripts/run_admission_autonomy.py started one normal WorkerLoop. reports/evolution/autonomous_admission_observation.json: 475.781 seconds, 23 cycles, 68 tasks completed, errors=[], no human prompts, five beneficial applications, candidate learn-8d88d82b4b4d49f7 consolidated normally as sem-cd3901dc11d943b6 by trust-system@low. Held-out certification 15 actual calls, 45.86 seconds, treatment5/5, baseline0/5, negative0/5.

FALTA: final suite completion, current-release persistence/recovery, stable longitudinal window and deployment-wide certification. Origin experience/training belong to earlier source revisions; current autonomous continuation is not all-stage same-SHA evidence. Continuous Evolution Supervisor remains unimplemented per upstream gate order.

RIESGO: original controlled experiment DB, not proof that main DB has absorbed this domain. Failed/aborted attempts preserved, including timeout and source-changing soak. No activation by insertion, wildcard routing, human impersonation or threshold changes.

SIGUIENTE PASO: finish frozen-source checks; publish truthful closure matrix and remaining gates.

FINAL CHECKPOINT: source a4fdde6; full suite 2763 passed/0 failed/0 skipped, frontend PASS. Passive soak 1812.891s/120 completed/0 failed. Natural resource recovery to full_local_guarded observed 2026-10-08T05:25Z. HECHO: experimental certification/application/consolidation/reuse, normal child crash recovery, controlled rollback. EVIDENCIA: FINAL_AUDIT.json. FALTA: same-SHA origin chain, main DB productive chain, deployed API productive crash recovery, continuous evolution supervisor. RIESGO: scoped evidence must not be represented as global certification. SIGUIENTE PASO: close origin correlation and deployed productive chain; LEVEL_8_CANDIDATE remains false.

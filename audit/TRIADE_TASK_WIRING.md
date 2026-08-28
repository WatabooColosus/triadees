# TRIADE · Cableado de tareas (generado)

Regenerar: `python scripts/build_system_inventory.py`

- módulos analizados: **791**
- clases: **617** · funciones: **6869**
- tipos de tarea declarados: **26**

| task_type | productor en producción | scripts | pruebas | ejecuciones |
|---|---|---|---|---|
| `bodega_global_review` | `triade/workers/mission_planner.py:591` | 0 | 0 | 2881 |
| `encrypted_backup` | `triade/workers/mission_planner.py:122` | 0 | 1 | 276 |
| `experimental_neuron_activity` | `triade/os/neuron_scheduler.py:253`, `triade/workers/mission_planner.py:1181` | 0 | 8 | 0 |
| `federation_inbox_review` | `triade/workers/mission_planner.py:1225` | 0 | 0 | 0 |
| `goal_install` | `triade/core/goal_orchestrator.py:333` | 0 | 1 | 0 |
| `goal_lora_train` | `triade/core/goal_orchestrator.py:385` | 0 | 1 | 0 |
| `goal_research` | **NINGUNO** | 0 | 1 | 6 |
| `goal_safe_command` | **NINGUNO** | 0 | 2 | 10 |
| `learning_candidate_deduplication` | `triade/workers/mission_planner.py:669` | 0 | 0 | 8688 |
| `learning_candidate_generation` | `triade/learning/post_run.py:125` | 0 | 0 | 721 |
| `learning_claim_distillation` | `triade/workers/mission_planner.py:725` | 0 | 0 | 1 |
| `learning_evidence_generation` | `triade/workers/mission_planner.py:843` | 1 | 0 | 1513 |
| `neural_learning_distribution` | `triade/workers/mission_planner.py:214` | 0 | 1 | 68 |
| `neuron_autopromotion` | `triade/workers/mission_planner.py:895` | 0 | 0 | 2328 |
| `neuron_candidate_formation` | `triade/workers/mission_planner.py:1363` | 0 | 1 | 2944 |
| `neuron_education_cycle` | `triade/workers/mission_planner.py:506` | 0 | 2 | 358 |
| `peft_canary_observation` | `triade/workers/mission_planner.py:1055` | 0 | 0 | 324 |
| `pending_learning_review` | `triade/evaluation/suites.py:67`, `triade/workers/mission_planner.py:611`, `triade/workers/mission_planner.py:933` | 0 | 2 | 651 |
| `pulse_check` | `triade/workers/mission_planner.py:574` | 8 | 55 | 22240 |
| `research_curriculum` | `triade/workers/mission_planner.py:240` | 0 | 0 | 286 |
| `self_improvement_canary_observation` | `triade/workers/mission_planner.py:437` | 0 | 0 | 0 |
| `self_improvement_evaluation` | `triade/workers/mission_planner.py:316`, `triade/workers/mission_planner.py:330` | 0 | 4 | 0 |
| `semantic_memory_governance` | `triade/workers/mission_planner.py:872` | 0 | 1 | 2794 |
| `stable_consolidation_review` | `triade/workers/mission_planner.py:1138` | 0 | 3 | 101 |
| `system_debt_scan` | `triade/workers/mission_planner.py:1268`, `triade/workers/mission_planner.py:1295` | 0 | 0 | 1352 |
| `write_governed_text_artifact` | **NINGUNO** | 0 | 0 | 4 |

## Tipos sin productor **literal** en producción

> Cuidado al leer esta lista: el análisis solo ve literales. Un tipo
> encolado con `task_type` en variable no aparece como producido aunque
> lo esté. Casos conocidos y **no** rotos:
>
> - `goal_research`, `goal_safe_command`, `write_governed_text_artifact`:
>   los produce `capability_resolver` → `goal_orchestrator`, que encola
>   `resolution.worker_task_type`. Son a petición del usuario, no
>   autónomos.
> - `bodega_global_review`: lo produce `os/event_engine.py` desde el
>   campo `action` de una regla, no desde un literal de tarea.
>
> `memory_consolidation_review` era el único huérfano real confirmado —
> `_plan_memory_consolidation()` encola `stable_consolidation_review`, no
> éste: dos nombres cercanos, uno muerto—. Se retiró el 2026-08-03 tras
> comprobar que su handler no avanzaba ningún candidato y que la vía de
> evidencia lo sustituye por completo. Sus 208 ejecuciones históricas
> siguen en la cola.

- `goal_research`
- `goal_safe_command`
- `write_governed_text_artifact`

## Variables `TRIADE_*` leídas por el código

- `TRIADE_ADAPTER_SIGNING_KEY`
- `TRIADE_ANDROID_APK`
- `TRIADE_ANDROID_BASE_MODEL`
- `TRIADE_ANDROID_LLAMA_CLI`
- `TRIADE_ANDROID_RUNTIME_DIR`
- `TRIADE_API_KEY`
- `TRIADE_AUDIT_API`
- `TRIADE_AUTH_DB_PATH`
- `TRIADE_AUTONOMY_LEVEL`
- `TRIADE_BACKUP_KEY`
- `TRIADE_BACKUP_KEY_FILE`
- `TRIADE_CLOUD_MODE`
- `TRIADE_CODE_VERSION`
- `TRIADE_CONTINUOUS_INTERVAL_SECONDS`
- `TRIADE_CONTINUOUS_MAX_CYCLES`
- `TRIADE_CONTINUOUS_RUNNER`
- `TRIADE_DB_PATH`
- `TRIADE_DISABLE_BACKGROUND`
- `TRIADE_E2E_BASE_URL`
- `TRIADE_ENFORCE_MODEL_POLICY`
- `TRIADE_FULL_CERT`
- `TRIADE_LIFE_PULSE_INTERVAL`
- `TRIADE_LIFE_REFLECTION_LIMIT`
- `TRIADE_MEASURED_ROUTING_PATH`
- `TRIADE_MOBILE_STATE`
- `TRIADE_NEURAL_LEARNING_ROUTING`
- `TRIADE_NODE_ID`
- `TRIADE_NODE_ONLINE_TTL_SECONDS`
- `TRIADE_NODE_SWEEP_SECONDS`
- `TRIADE_NODE_TOKEN`
- `TRIADE_OLLAMA_BIN`
- `TRIADE_PAIRING_TOKEN`
- `TRIADE_POST_RUN_LEARNING`
- `TRIADE_PUBLIC_GUARDED`
- `TRIADE_RATE_LIMIT_PER_MINUTE`
- `TRIADE_REAL_E2E`
- `TRIADE_REDIS_URL`
- `TRIADE_RELAY_ADMIN_TOKEN`
- `TRIADE_RELAY_DB`
- `TRIADE_RELAY_PAIRING_TOKEN`
- `TRIADE_RELAY_TOKEN_FILE`
- `TRIADE_RELAY_URL`
- `TRIADE_RUNS_DIR`
- `TRIADE_RUNTIME_INTERVAL_SECONDS`
- `TRIADE_RUNTIME_MAX_CYCLES`
- `TRIADE_RUNTIME_MODE`
- `TRIADE_RUNTIME_SCOPE`
- `TRIADE_RUNTIME_URL`
- `TRIADE_RUN_CONCURRENCY`
- `TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE`
- `TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE_MIN_CONFIDENCE`
- `TRIADE_SELF_IMPROVEMENT_POLICY_AUTHORIZER`
- `TRIADE_SELF_TEST_EVERY_CYCLES`
- `TRIADE_STUDIO_PORT`
- `TRIADE_SYNTHETIC_CANARY`
- `TRIADE_TEST_ROOT`
- `TRIADE_WATCHDOG_INTERVAL`
- `TRIADE_WATCHDOG_MAX_RECOVERIES`
- `TRIADE_WATCHDOG_RECOVERY_COOLDOWN_SECONDS`
- `TRIADE_WORKER_CONCURRENCY`
- `TRIADE_WORKER_EVENTS_RETENTION`


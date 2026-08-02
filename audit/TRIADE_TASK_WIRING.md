# TRIADE · Cableado de tareas (generado)

Regenerar: `python scripts/build_system_inventory.py`

- módulos analizados: **714**
- clases: **641** · funciones: **6066**
- tipos de tarea declarados: **24**

| task_type | productor en producción | scripts | pruebas | ejecuciones |
|---|---|---|---|---|
| `bodega_global_review` | **NINGUNO** | 0 | 0 | 0 |
| `encrypted_backup` | `triade/workers/mission_planner.py:85` | 0 | 0 | 13 |
| `experimental_neuron_activity` | `triade/os/neuron_scheduler.py:247`, `triade/workers/mission_planner.py:544` | 0 | 8 | 0 |
| `federation_inbox_review` | `triade/workers/mission_planner.py:588` | 0 | 0 | 0 |
| `goal_install` | `triade/core/goal_orchestrator.py:159` | 0 | 0 | 0 |
| `goal_lora_train` | `triade/core/goal_orchestrator.py:197` | 0 | 0 | 0 |
| `goal_research` | **NINGUNO** | 0 | 0 | 3 |
| `goal_safe_command` | **NINGUNO** | 0 | 2 | 5 |
| `learning_candidate_deduplication` | `triade/workers/mission_planner.py:317` | 0 | 0 | 428 |
| `learning_candidate_generation` | `triade/learning/post_run.py:99` | 0 | 0 | 4 |
| `learning_evidence_generation` | `triade/workers/mission_planner.py:339` | 0 | 0 | 454 |
| `memory_consolidation_review` | **NINGUNO** | 0 | 1 | 0 |
| `neuron_autopromotion` | `triade/workers/mission_planner.py:381` | 0 | 0 | 349 |
| `neuron_candidate_formation` | `triade/workers/mission_planner.py:664` | 0 | 1 | 417 |
| `neuron_education_cycle` | `triade/workers/mission_planner.py:246` | 0 | 0 | 15 |
| `pending_learning_review` | `triade/workers/mission_planner.py:291`, `triade/workers/mission_planner.py:419`, `triade/evaluation/suites.py:67` | 0 | 2 | 215 |
| `pulse_check` | `triade/workers/mission_planner.py:272` | 8 | 44 | 1930 |
| `research_curriculum` | `triade/workers/mission_planner.py:124` | 0 | 0 | 79 |
| `self_improvement_canary_observation` | `triade/workers/mission_planner.py:205` | 0 | 0 | 0 |
| `self_improvement_evaluation` | `triade/workers/mission_planner.py:160` | 0 | 4 | 0 |
| `semantic_memory_governance` | `triade/workers/mission_planner.py:358` | 0 | 1 | 0 |
| `stable_consolidation_review` | `triade/workers/mission_planner.py:501` | 0 | 3 | 0 |
| `system_debt_scan` | `triade/workers/mission_planner.py:630` | 0 | 0 | 290 |
| `write_governed_text_artifact` | **NINGUNO** | 0 | 0 | 0 |

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
> El único huérfano real confirmado es `memory_consolidation_review`:
> `_plan_memory_consolidation()` encola `stable_consolidation_review`,
> no éste. Dos nombres cercanos, uno muerto.

- `bodega_global_review`
- `goal_research`
- `goal_safe_command`
- `memory_consolidation_review`
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
- `TRIADE_ENFORCE_MODEL_POLICY`
- `TRIADE_LIFE_PULSE_INTERVAL`
- `TRIADE_LIFE_REFLECTION_LIMIT`
- `TRIADE_MEASURED_ROUTING_PATH`
- `TRIADE_MOBILE_STATE`
- `TRIADE_NODE_ID`
- `TRIADE_NODE_ONLINE_TTL_SECONDS`
- `TRIADE_NODE_SWEEP_SECONDS`
- `TRIADE_NODE_TOKEN`
- `TRIADE_OLLAMA_BIN`
- `TRIADE_PAIRING_TOKEN`
- `TRIADE_POST_RUN_LEARNING`
- `TRIADE_PUBLIC_GUARDED`
- `TRIADE_RATE_LIMIT_PER_MINUTE`
- `TRIADE_REDIS_URL`
- `TRIADE_RELAY_ADMIN_TOKEN`
- `TRIADE_RELAY_DB`
- `TRIADE_RELAY_PAIRING_TOKEN`
- `TRIADE_RELAY_TOKEN_FILE`
- `TRIADE_RELAY_URL`
- `TRIADE_RUNTIME_INTERVAL_SECONDS`
- `TRIADE_RUNTIME_MAX_CYCLES`
- `TRIADE_RUNTIME_MODE`
- `TRIADE_RUNTIME_SCOPE`
- `TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE`
- `TRIADE_SELF_TEST_EVERY_CYCLES`
- `TRIADE_SYNTHETIC_CANARY`
- `TRIADE_TEST_ROOT`
- `TRIADE_WATCHDOG_INTERVAL`
- `TRIADE_WATCHDOG_MAX_RECOVERIES`
- `TRIADE_WATCHDOG_RECOVERY_COOLDOWN_SECONDS`
- `TRIADE_WORKER_CONCURRENCY`
- `TRIADE_WORKER_EVENTS_RETENTION`


# Observability — Tríade Ω

## Objetivo

La fase OBS endurece Tríade como sistema local 24/7 verificable: los fallos
internos no se silencian, las misiones neuronales se conectan con aprendizaje y
memoria, y la UI consume estado operativo real.

## Error Bus

`triade/core/error_bus.py` registra errores internos en `worker_events` con:

- `scope`: módulo o subsistema (`life_pulse.continuous.runner_run`, `mission_planner.baseline`, etc.)
- `run_id` y `task_id` cuando existen
- `payload.context.module`
- `payload.context.function`
- `payload.context.operation`
- `traceback` truncado

Consulta:

```bash
GET /api/internal/errors
GET /api/internal/errors?scope=mission_planner.baseline
```

## Continuous Runner

`LifePulseEngine._continuous_loop()` conserva backoff exponencial y registra
fallos de:

- formación de candidatos
- entrenamiento de candidatos
- recomputación de trust
- `TriadeRunner.run()` profundo
- activación experimental ligera
- `build_system_dict`
- `build_system_pulse_text`

El hilo actualiza `continuous_runner.last_error` y registra en `error_bus`
antes de seguir o aplicar backoff.

## Trazabilidad de Aprendizaje

`record_learning_usage_from_output()` detecta uso de aprendizaje por:

1. `output.memory_diff.used_learning_candidate_ids`
2. `memory.semantic_recall.authorized_matches[].document_id`
3. `output.memory_diff.evidence_refs`
4. overlap heurístico como fallback

La trazabilidad del output incluye:

- `used_learning_candidate_ids`
- `used_semantic_document_ids`
- `used_neuron_mission_ids`
- `evidence_refs`
- `match_sources`
- `heuristic_matches`

Los matches heurísticos quedan marcados con `heuristic_match=True`.

## MissionPlanner

Cada tarea planificada contiene `reason`, `source` y `planner_score`.

Baseline:

- `pulse_check`: siempre
- `pending_learning_review`: solo si hay candidatos
- `semantic_memory_governance`: solo si hay documentos `candidate` o `experimental`
- `neuron_autopromotion`: solo si hay training o evidencia promovible

Toda consulta SQL fallida registra `internal_error` con la operación que falló.

## Endpoints Operativos

```text
GET /api/internal/errors
GET /api/internal/errors?scope=
GET /api/workers/events
GET /api/neurons/missions
GET /api/neurons/missions/{id}
GET /api/neurons/missions/{id}/cycles
GET /api/neurons/missions/{id}/evidence
GET /api/neurons/missions/{id}/scores
GET /api/system/life
GET /api/learning/pending
```

## UI

La pestaña **Observabilidad** muestra datos reales de:

- errores internos recientes
- misiones neuronales activas
- aprendizajes verificados usados recientemente
- estado del continuous runner
- eventos recientes de workers

## Límites de Seguridad

- `identity_core` no se modifica automáticamente.
- Los workers siguen limitados a tareas internas conocidas.
- No se habilita shell libre.
- No se habilita red libre en workers.

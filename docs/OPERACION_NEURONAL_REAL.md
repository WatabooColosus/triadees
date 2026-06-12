# Operación Neuronal Real

Este documento describe el MVP local verificable de Tríade Ω. No describe conciencia humana ni capacidades externas automáticas: el sistema observa, registra, evalúa y propone aprendizaje con trazabilidad local.

## De Dónde Sacan Información

Las neuronas leen señales locales del sistema: runs, memoria episódica, memoria semántica autorizada, actividad neuronal, misiones, ciclos, evidencia, scores, QualiaBus, worker events y estado de LifePulse.

Las misiones activas se guardan en `neuron_missions`. Cuando `MissionPlanner` agenda `experimental_neuron_activity` con `mission_id`, `WorkerLoop` llama a `NeuronMissionExecutor`, que trabaja sin shell ni red por defecto.

## Cómo Se Entrenan

Una neurona candidata puede recibir training desde el pipeline de formación y desde evidencias de ejecución. El entrenamiento no equivale a memoria estable. Produce scores, warnings, recomendaciones y estado de revisión.

Las misiones generan evidencia real en:

- `neuron_work_cycles`
- `neuron_evidence`
- `neuron_scores`
- `learning_queue` si la misión tiene permiso `propose_learning`

## Quién Programa Y Ejecuta

`MissionPlanner` decide qué tareas de worker se encolan, con `reason`, `source` y `planner_score`.

`WorkerLoop` ejecuta tareas locales y registra eventos. Para misiones neuronales, delega a `NeuronMissionExecutor`.

`LifePulse` observa el sistema periódicamente. Su continuous runner está apagado por defecto y solo opera si se activa con `TRIADE_CONTINUOUS_RUNNER=1` o con el endpoint runtime explícito.

## Central, Hipotálamo Y Bodega

Hipotálamo clasifica señales de intención, urgencia y riesgo.

Central planifica y responde, pero las contribuciones neuronales solo se usan si pasan filtros de riesgo, confianza y Safety.

Bodega registra runs, episodios, señales, cristales, reportes y memoria. El aprendizaje estable no se escribe directamente desde neuronas ni workers: pasa por `LearningPipeline`.

QualiaBus recibe experiencias y puede crear candidatos de aprendizaje, siempre como candidatos trazables.

## Cuándo Puede Decir “Ya Aprendí”

Una neurona no puede decir “ya aprendí” por emitir texto o una observación.

Puede decir “propuse aprendizaje” cuando existe un candidato en `learning_queue` con `source_ref` trazable.

Puede decir “ya aprendí” solo cuando el candidato completa el ciclo:

`candidate -> evaluated -> verified -> validated_in_runs -> consolidated`

La consolidación estable exige source_ref, uso real en runs, outcome suficiente y protección de `identity_core`.

## Evidencia Mínima Candidate → Experimental → Stable

Candidate: contrato, misión, dominio, reglas y training inicial.

Experimental: score/training suficiente, permiso explícito o autopromoción controlada, y actividad auditable.

Stable: evidencia diversa. No bastan activaciones sintéticas. Se requiere actividad no sintética, verificaciones externas o runs reales, y decisión humana cuando el endpoint lo exige.

## Background Seguro

Default seguro:

```bash
unset TRIADE_CONTINUOUS_RUNNER
uvicorn apps.single_port_app:app --host 0.0.0.0 --port 8010
```

Activación por entorno:

```bash
TRIADE_CONTINUOUS_RUNNER=1 \
TRIADE_AUTONOMY_LEVEL=observe_only \
TRIADE_CONTINUOUS_INTERVAL_SECONDS=10 \
uvicorn apps.single_port_app:app --host 0.0.0.0 --port 8010
```

Activación runtime, sin cambiar default persistente:

```bash
curl -X POST http://127.0.0.1:8010/api/system/life/continuous-runner \
  -H 'Content-Type: application/json' \
  -d '{"enabled": true, "autonomy_level": "observe_only", "interval_seconds": 10, "max_cycles": 3}'
```

Desactivar runtime:

```bash
curl -X POST http://127.0.0.1:8010/api/system/life/continuous-runner \
  -H 'Content-Type: application/json' \
  -d '{"enabled": false}'
```

## Comandos Locales

Tests:

```bash
python -m pytest -q
```

Servidor:

```bash
uvicorn apps.single_port_app:app --host 0.0.0.0 --port 8010
```

Health:

```bash
curl http://127.0.0.1:8010/api/health
curl http://127.0.0.1:8010/api/system/pulse
curl http://127.0.0.1:8010/api/internal/errors
```

Workers:

```bash
curl http://127.0.0.1:8010/workers/status
curl http://127.0.0.1:8010/workers/events
curl -X POST http://127.0.0.1:8010/workers/run-once
```

Neuronas y misiones:

```bash
curl http://127.0.0.1:8010/api/system/neurons/full
curl http://127.0.0.1:8010/api/neurons/missions
curl http://127.0.0.1:8010/api/neuron_missions/1/cycles
curl http://127.0.0.1:8010/api/neuron_missions/1/evidence
curl http://127.0.0.1:8010/api/neuron_missions/1/scores
```

## Error Bus Y Retención

`error_bus` registra errores internos en `worker_events` con severidad:

- `critical`: riesgo de identidad, memoria estable o Safety.
- `error`: fallo interno recuperable.
- `warning`: degradación controlada, timeout o fallback.
- `info`: diagnóstico no bloqueante.

La retención básica de `worker_events` conserva los últimos `TRIADE_WORKER_EVENTS_RETENTION` eventos. Default: `5000`. Usa `0` o negativo para desactivar pruning.

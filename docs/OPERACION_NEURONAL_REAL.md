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

## Runtime Interno 24/7

El chat no es el motor de pensamiento. El motor interno es el runtime supervisor que observa, planifica, ejecuta misiones y procesa aprendizaje en segundo plano con límites explícitos.

Modos de autonomía:

- `observe_only`: observa y registra eventos; no crea aprendizaje.
- `learn_candidates`: puede crear learning candidates desde gaps, errores o señales operativas.
- `execute_missions`: ejecuta misiones activas, registra ciclos/evidencia/scores y puede proponer aprendizaje.
- `full_local`: combina observación, misiones y evaluación de candidates, sin tocar `identity_core` ni escribir memoria estable directa.

Comandos:

```bash
python triade_digimon.py runtime status
python triade_digimon.py runtime once
python triade_digimon.py runtime start
python triade_digimon.py runtime stop
python triade_digimon.py runtime events
python triade_digimon.py runtime context
python triade_digimon.py runtime report
```

API:

```bash
curl http://127.0.0.1:8010/api/runtime/status
curl -X POST http://127.0.0.1:8010/api/runtime/once
curl -X POST http://127.0.0.1:8010/api/runtime/start
curl -X POST http://127.0.0.1:8010/api/runtime/stop
curl http://127.0.0.1:8010/api/runtime/events
curl http://127.0.0.1:8010/api/runtime/context
curl http://127.0.0.1:8010/api/system/living-context
curl http://127.0.0.1:8010/api/system/living-report
```

`build_living_context_for_chat()` arma el contexto interno para la Central. Ese contexto incluye runtime, workers, misiones, learning, Qualia, modelos, errores y política de confianza. La Central puede responder desde ese estado vivo, no solo desde el último turno.

`build_living_report()` resume si la Tríade está pensando sin chat: ciclos recientes, misiones ejecutadas, candidates creados, estado de workers, modelos y política de seguridad.

## Activar Misiones Desde Neuronas Existentes

Cuando `mission_count = 0`, el sistema todavía tiene neuronas registradas pero no tiene contratos operativos creados para ellas. En ese caso, primero hay que poblar `neuron_missions` desde el registro existente.

Comandos:

```bash
python triade_digimon.py neuron-missions doctor
python triade_digimon.py neuron-missions backfill
python triade_digimon.py workers once
python triade_digimon.py neuron-missions doctor
```

API equivalente:

```bash
curl http://127.0.0.1:8010/api/neuron_missions/doctor
curl -X POST http://127.0.0.1:8010/api/neuron_missions/backfill
curl -X POST http://127.0.0.1:8010/workers/run-once
```

`backfill` crea una misión por neurona activa si aún no existe. Usa el nombre, misión y dominio reales de la neurona, y mantiene bloqueadas las acciones peligrosas. No crea memoria estable ni modifica `identity_core`.

Después del backfill, `MissionPlanner` ya puede encolar `experimental_neuron_activity` con `mission_id`. `WorkerLoop` entonces ejecuta `NeuronMissionExecutor`, que registra ciclos, evidencia, scores y, si está permitido, candidatos en `learning_queue`.

`doctor` sirve para verificar:

- `total_neurons`
- `total_missions`
- `missions_by_status`
- `missions_without_cycles`
- `missions_with_evidence`
- `mission_learning_candidates`
- `ready_to_execute_count`

`learning_candidate` no es memoria estable. Sigue siendo un candidato hasta que `LearningPipeline` lo evalúa, verifica, valida en runs y consolida.

## Auditoría De Neuronas Stable

La etiqueta `stable` no se toma como verdad automática. El auditor read-only revisa evidencia actual y separa:

- `keep_stable`: la neurona sigue en stable.
- `mark_needs_review`: la neurona requiere revisión humana.
- `demote_to_experimental`: la neurona estable no tiene evidencia mínima.

Comandos:

```bash
python triade_digimon.py neuron audit-stable
python triade_digimon.py neuron audit-stable --apply
```

API:

```bash
curl http://127.0.0.1:8010/api/neurons/stable-audit
curl -X POST http://127.0.0.1:8010/api/neurons/stable-audit/apply
```

La auditoría no borra datos, no modifica `identity_core` y no consolida memoria estable. Solo deja evidencia operativa y, si se aplica explícitamente, cambia el estado de la neurona auditada para reflejar la revisión.

## Coherencia De Respuesta

La salida final pasa por `ResponseCoherenceGate` antes de persistirse.

- Feedback positivo, agradecimientos y cierres emocionales no repiten la respuesta anterior.
- Un follow-up real sí puede reutilizar el contexto previo.
- Un cambio de tema corta el arrastre contextual si la respuesta propuesta se pegó al turno anterior.
- La salida final guarda trazabilidad en `response_coherence_gate` y en `memory_diff.traceability`.

Ejemplos:

- `"muy bine, felicitaciones"` → agradece el feedback y no repite el dato factual anterior.
- `"y cuál es su capital?"` → se trata como seguimiento y puede usar el contexto anterior.
- `"gracias"` o `"ok perfecto"` → se responde breve, sin arrastrar la respuesta previa.

## Qué No Debe Convertirse En Neurona

`NeuronCandidateGate` evita crear neuronas literales cuando el input no tiene valor operativo repetible.

No se crea neurona para:

- preguntas factuales simples;
- felicitaciones;
- agradecimientos;
- frases casuales sin misión clara;
- correcciones menores;
- conocimiento puntual que cabe en una sola respuesta.

En esos casos el sistema puede:

- registrar feedback en Qualia;
- dejar el hecho como aprendizaje candidato;
- guardar el episodio para contexto futuro;
- no confundir una observación con una neurona operativa.

Solo se crea neurona cuando hay petición explícita o necesidad operativa repetible con evidencia trazable. La memoria estable sigue protegida por `LearningPipeline`.

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

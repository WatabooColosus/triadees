# Neuron Missions — Sistema de Misiones Neuronales

## Visión General

Las misiones neuronales son la capa que convierte a las neuronas de módulos informativos en agentes internos de trabajo, aprendizaje y validación en segundo plano.

Cada neurona activa tiene una **misión** que define:
- Qué investiga (dominio)
- De qué fuentes puede aprender (fuentes permitidas)
- Qué acciones puede ejecutar (acciones permitidas)
- Cómo se mide su progreso (métricas)
- Qué tan seguido trabaja (schedule)

## Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│                    MissionPlanner                        │
│  Lee estado real del sistema → produce tareas priorizadas │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────┐
│                  WorkerScheduler                         │
│  MissionPlanner → WorkerTaskQueue → WorkerLoop           │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────┐
│                   WorkerLoop                             │
│  Ejecuta tareas con sandbox, safety review, qualia       │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────┐
│              NeuronMissionStore                          │
│  Persiste misiones, ciclos, evidencia, scores en SQLite  │
└─────────────────────────────────────────────────────────┘
```

## Ciclo de Vida de una Misión

```
candidate → experimental → stable → paused | rejected
```

- **candidate**: Misión creada, esperando activación
- **experimental**: Misión activa, la neurona trabaja en segundo plano
- **stable**: Misión consolidada con evidencia suficiente
- **paused**: Misión pausada temporalmente
- **rejected**: Misión rechazada

## Cómo se Crea una Misión

### Via API
```bash
POST /api/neurons/missions
{
  "title": "Investigar edge computing",
  "mission": "Analizar patrones de edge computing en dispositivos móviles",
  "domain": "federation_android_edge",
  "neuron_id": 1,
  "allowed_sources": ["worker", "federation"],
  "allowed_actions": ["observe", "diagnose", "propose_learning"],
  "schedule_hint": "every_cycle",
  "status": "candidate"
}
```

### Via Código
```python
from triade.core.neuron_missions import NeuronMission, NeuronMissionStore

store = NeuronMissionStore()
mission = NeuronMission(
    neuron_id=1,
    title="Investigar edge computing",
    mission="Analizar patrones de edge computing",
    domain="federation_android_edge",
    status="experimental",
)
mission_id = store.create_mission(mission)
```

## Cómo Trabaja en Segundo Plano

El `MissionPlanner` lee el estado real del sistema cada ciclo:

1. **Tareas base** (siempre se ejecutan):
   - `pulse_check` — Verificación de pulso del sistema
   - `pending_learning_review` — Revisión de pipeline de aprendizaje
   - `semantic_memory_governance` — Gobierno de memoria semántica
   - `neuron_autopromotion` — Revisión de autopromoción neuronal

2. **Tareas condicionales** (según estado):
   - Candidatos de aprendizaje pendientes → `pending_learning_review`
   - Tareas fallidas recientes → reintento
   - Memoria verificada pendiente → `memory_consolidation_review`
   - Misiones activas → `experimental_neuron_activity`
   - Mensajes federados → `federation_inbox_review`
   - Deuda del sistema → `system_debt_scan`
   - Candidatos neuronales sin training → `neuron_candidate_formation`

Cada tarea encolada incluye en su payload:
- `reason`: Por qué se programó esta tarea
- `source`: De dónde viene la decisión (mission_planner, mission_planner_baseline, etc.)
- `planner_score`: Prioridad numérica (menor = más urgente)
- `related_neuron_id`: ID de la neurona relacionada (opcional)
- `related_candidate_id`: ID del candidato relacionado (opcional)

## Cómo Aprende

1. La neurona ejecuta su misión (observa, diagnostica, propone)
2. Los resultados se registran como **evidencia** en `neuron_evidence`
3. Los **ciclos de trabajo** se registran en `neuron_work_cycles`
4. Los **scores** se calculan y registran en `neuron_scores`

## Cuándo Dice "Ya Aprendí"

La neurona indica que ha aprendido cuando:
- Tiene evidencia suficiente (múltiples observaciones consistentes)
- Sus scores superan umbrales
- Ha ejecutado ciclos de trabajo exitosos
- La evidencia es diversa (no solo de una fuente)

## Cómo Pasa de Experimental a Stable

El `NeuronAutopromoter` evalúa:
1. **Evidencia diversa**: Al menos 1 activación no sintética
2. **Verificaciones externas**: Al menos 1 run real del runner
3. **Thresholds clásicos**: 5 activaciones, 5 diagnósticos, 3 test plans
4. **No solo experimental_light_pulse**: Requiere evidencia de runs de usuario, tests o workers

## Cómo la Central y el Hipotálamo Usan las Neuronas

- La **Central** recibe contribuciones neuronales filtradas por risk/confidence/Safety
- El **Hipotálamo** modula tono/riesgo/urgencia desde señales internas
- Las neuronas proponen diagnósticos, aprendizaje e influencias
- Todo queda registrado en `neuron_contributions` y `neuron_learning_candidates`

## Cómo la Bodega Almacena Evidencia y Memoria

- **Evidencia**: `neuron_evidence` (SQLite) — observaciones, diagnósticos, scores
- **Ciclos**: `neuron_work_cycles` (SQLite) — registros de trabajo
- **Scores**: `neuron_scores` (SQLite) — métricas de progreso
- **Misiones**: `neuron_missions` (SQLite) — definiciones de trabajo
- **Memoria estable**: Solo se escribe con `source_ref`, validación y gates del LearningPipeline

## Endpoints API

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/neurons/missions` | Lista misiones (filtro por status) |
| POST | `/api/neurons/missions` | Crea nueva misión |
| GET | `/api/neurons/missions/{neuron_id}` | Misiones de una neurona |
| GET | `/api/neurons/missions/{neuron_id}/cycles` | Ciclos de trabajo |
| GET | `/api/neurons/missions/{neuron_id}/evidence` | Evidencia reciente |

## Tablas SQLite

| Tabla | Descripción |
|-------|-------------|
| `neuron_missions` | Definiciones de misiones |
| `neuron_work_cycles` | Registros de ciclos de trabajo |
| `neuron_evidence` | Evidencia observada |
| `neuron_scores` | Scores de progreso |

## Tests

```bash
python -m pytest tests/test_neuron_missions.py -v
python -m pytest tests/test_mission_planner.py -v
python -m pytest tests/test_scheduler_mission_planner.py -v
python -m pytest tests/test_learning_usage_from_output.py -v
```

## Seguridad

- **identity_core** nunca se modifica
- **Memoria estable** solo se escribe con gates del LearningPipeline
- **Shell y red** no se habilitan en workers
- **Safety review** se ejecuta antes de cada tarea
- **Sandbox** aísla ejecución de tareas internas

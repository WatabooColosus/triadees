# Neuron Mission Executor

`triade/workers/neuron_mission_executor.py` convierte una misión neuronal activa en trabajo auditable.

Una neurona trabaja cuando `MissionPlanner` agenda una tarea `experimental_neuron_activity` con `mission_id`. `WorkerLoop` detecta ese payload y llama a `NeuronMissionExecutor.execute(...)`. El executor solo acepta misiones con status `experimental` o `stable`; misiones `candidate`, `paused` o `rejected` quedan bloqueadas.

El ciclo es local y seguro: no abre shell, no usa red, no escribe `identity_core` y no consolida memoria estable. El contexto de trabajo se construye con título, misión, dominio, fuentes permitidas, acciones permitidas, ciclos recientes, evidencia reciente y último score.

## Evidencia

Cada ejecución registra:

- `NeuronWorkCycle`: resumen de entrada, resumen de salida, refs de evidencia, duración y status.
- `NeuronEvidence`: observación y diagnóstico serializados, refs trazables y score del ciclo.
- `NeuronScore`: componentes del score y valor compuesto.

Todas las refs incluyen `mission_id` y `run_ref`, por ejemplo `mission:7`, `run:worker-...`, `mission:7:evidence:3`.

## Aprendizaje

El executor siempre puede observar y diagnosticar si la misión lo permite por contrato. También puede producir una hipótesis en `proposed_learning`, pero solo la envía a `LearningPipeline.ingest` cuando `propose_learning` está en `allowed_actions`.

El candidato se crea como:

- `source_type="tool"`
- `source_ref="mission:{mission_id}:run:{run_ref}"`
- `risk_level="low"`
- `domain=mission.domain`

Esto nutre `learning_queue`, no memoria estable.

## Cuándo Puede Decir “Aprendí”

Una misión no puede decir que aprendió solo por observar o proponer. Puede decir “propuse aprendizaje” cuando creó un candidato en `learning_queue`.

Puede decir “aprendí” únicamente cuando el `LearningPipeline` complete sus gates posteriores: `candidate -> evaluated -> verified -> validated_in_runs -> consolidated`. La consolidación estable sigue protegida por el pipeline y requiere evidencia de uso suficiente.

## Observar, Proponer Y Consolidar

Observar: registrar un ciclo y evidencia local sobre la misión.

Proponer aprendizaje: crear un candidato trazable en `learning_queue` si la misión tiene permiso `propose_learning`.

Consolidar memoria estable: paso posterior del `LearningPipeline`; no lo hace `NeuronMissionExecutor`.

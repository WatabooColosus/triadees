# Technical Debt Map · Tríade Ω

Este documento registra deuda técnica prioritaria detectada durante la revisión de `main`.

## Prioridad 0 · Higiene Git y operación segura

- Evitar escritura directa a `main` desde asistentes o automatizaciones.
- Flujo recomendado: rama de trabajo → commit → pull request → revisión → merge.
- Mantener archivos de prueba fuera de `main` salvo que formen parte de fixtures controlados.

## Prioridad 1 · Separación de UI, API y núcleo

`apps/single_port_app.py` concentra demasiadas responsabilidades y supera las 2200 líneas. Debe dividirse gradualmente en:

- rutas FastAPI,
- servicios de aplicación,
- capa de UI,
- schemas de request/response,
- adaptadores de estado,
- utilidades compartidas.

Objetivo: que la UI pueda evolucionar sin tocar el núcleo cognitivo.

## Prioridad 2 · Runner cognitivo demasiado concentrado

`triade/core/runner.py` coordina modelos, memoria, cristal, safety, aprendizaje, neuronas, artefactos e integridad. Aunque funciona como orquestador MVP, conviene extraer responsabilidades en servicios:

- `ModelSelectionService`,
- `SemanticRecallService`,
- `RunArtifactService`,
- `LearningCandidateService`,
- `NeuronOrchestrationService`,
- `OutputGateService`.

Objetivo: mantener `TriadeRunner.run()` como pipeline legible y testeable.

## Prioridad 3 · Contratos de datos

`triade/core/contracts.py` usa `dataclasses` para evitar dependencias en MVP. Es válido, pero debe definirse una ruta de migración parcial o total a validación fuerte:

- Pydantic opcional para API,
- validadores manuales para entorno liviano,
- pruebas de serialización/deserialización,
- compatibilidad hacia atrás de artefactos `runs/`.

## Prioridad 4 · Safety como compuerta real

El README define estados como `approved`, `approved_with_warning`, `sandbox_only`, `requires_human_approval` y `blocked`. Debe comprobarse que esos estados actúen como compuertas efectivas antes de acciones sensibles, no solo como metadatos.

Tareas:

- tests unitarios de bloqueo,
- tests de `requires_human_approval`,
- separación entre respuesta conversacional y acción ejecutable,
- auditoría de acciones permitidas por estado.

## Prioridad 5 · Federación y nodos

La federación aparece como visión central, pero debe endurecerse como capa verificable independiente:

- registro de nodos,
- autenticación,
- permisos por recurso,
- trazabilidad de intercambio,
- límites de acceso a memoria,
- pruebas de nodo simulado.

## Prioridad 6 · Batería de pruebas

Agregar pruebas mínimas para:

- ciclo cognitivo completo,
- creación de run y artefactos,
- memoria y recall,
- cristal temporal,
- safety,
- output gate,
- API/UI smoke tests,
- federación simulada,
- compatibilidad de contratos.

## Prioridad 7 · UI futura

Antes de rediseñar la interfaz, preparar separación técnica:

- endpoints estables,
- estado serializable,
- componentes UI aislados,
- modo legacy preservado,
- smoke test de `/`, `/ui` y `/api/ui/legacy`.

## Regla operativa recomendada

Toda intervención asistida por GPT o agentes externos debe seguir:

```text
no main directo → rama → PR → revisión humana → merge
```

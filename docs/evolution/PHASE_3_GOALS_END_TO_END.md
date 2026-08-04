# Fase 3 — Goals end-to-end

## SHA base, rama y objetivo

- SHA base: `297d427bf51578c004e5b20d5fa962492d4a405d`.
- Rama: `phase/03-goals-end-to-end`.
- Objetivo: demostrar y gobernar `input → capability resolver → goal → plan → task → execution → result → close → learning`.

## Estado inicial

El código existente contenía `CapabilityResolver`, `GoalOrchestrator`,
`PlanningGraph`, la cola canónica y handlers de worker. Era alcanzable desde el
preflight del Runner, pero las pruebas sólo cubrían pregunta, orden segura,
aprobación y dos resultados bloqueados. Eso no demostraba el ciclo completo.

En concreto:

- `PlanningGraph.update_status()` aceptaba cualquier texto como estado;
- ninguna transición registraba productor, motivo o evidencia;
- dos peticiones idénticas creaban dos goals y dos planes;
- no había operaciones de cancelación, expiración o reconciliación;
- los reintentos volvían a `queued` sin estado ni evento de replanificación;
- una petición ambigua dependía del resultado de expresiones regulares;
- cuatro filas históricas —dos roots y sus pasos— seguían en
  `awaiting_approval` desde el 29 de julio y el 1 de agosto de 2026;
- un resultado exitoso cerraba el goal, pero no declaraba si había o no señal de
  aprendizaje;
- el endpoint de estado podía presentar `artifact_publication_pending` como
  error de una tarea ya completada.

## Causa

La persistencia del estado se había implementado antes que el contrato del
ciclo de vida. Existían productores y consumidores parciales, pero no una
máquina de estados, un ledger de transiciones ni una política común para salir
de estados no terminales.

## Cambios

### Resolución de intención

`CapabilityResolver.classify()` combina tokens normalizados, modalidad,
interrogación, alternativas y verbos de acción. Las regex continúan enrutando
la capacidad concreta, pero ya no deciden por sí solas si se abre un goal.

- pregunta → conversación, cero goals;
- orden ambigua → `needs_clarification`, cero goals;
- orden explícita → resolución gobernada;
- alternativas explícitas o modalidad dudosa → aclaración.

### Máquina de estados y auditoría

Estados válidos:

`pending`, `awaiting_approval`, `queued`, `running`, `replanning`,
`completed`, `blocked`, `failed`, `expired`, `cancelled`, `archived`.

Terminales:

`completed`, `blocked`, `failed`, `expired`, `cancelled`, `archived`.

Toda transición valida origen/destino y escribe `goal_events` con actor, razón,
evidencia y timestamp. Un terminal no puede reabrirse; sólo puede archivarse.

### Deduplicación

Cada root recibe un `request_key` SHA-256 sobre fuente y petición normalizada.
Si existe un goal activo con la misma clave, se devuelve el goal y task
existentes, y se registra `duplicate_rejected`. No se crean filas nuevas.

### Cierre, replanificación y aprendizaje

- éxito → paso y root `completed`;
- gate bajo o ausencia de evidencia → `blocked`;
- error con presupuesto → `replanning` y nueva tarea `queued`;
- presupuesto agotado → `failed`;
- cada cierre escribe una `goal_learning_observation`.

La observación distingue `failure_signal` de `no_learning_signal`. Esta última
es deliberada: una ejecución correcta no equivale por sí sola a aprendizaje y
no crea un candidato artificial.

### Operación y limbo histórico

Se añadieron entrypoints protegidos para cancelar y expirar. El reconciliador
es explícito, aditivo y no se ejecuta al importar o arrancar.

El 4 de agosto de 2026 se ejecutó contra el SQLite observado:

- roots examinados: 2;
- pasos asociados: 2;
- filas eliminadas: 0;
- decisión: 4 filas `awaiting_approval` → `expired`;
- causa: preguntas antiguas mal clasificadas y sin aprobación posible;
- roots activos antiguos después: 0;
- rollback exacto: incluido en `artifacts/evolution/phase_3_results.json`.

## Código existente, alcanzable y demostrado

| Nivel | Evidencia |
|---|---|
| Código existente | Resolver, orquestador, grafo, cola y worker ya existían. |
| Código alcanzable | Runner preflight y API llaman al orquestador. |
| Código probado | Suite específica cubre los once casos obligatorios. |
| Código ejecutado | Un diagnóstico real atravesó cola, lease, handler, artefacto y cierre. |
| Runtime observado | Dos roots históricos y dos pasos fueron clasificados y expirados sin borrado. |
| Capacidad demostrada | Orden diagnóstica: input → resolver → root/paso → tarea → worker → resultado → cierre → observación. |

## Casos obligatorios

| Caso | Resultado válido | Evidencia |
|---|---|---|
| orden válida | `completed` | worker real y artefacto |
| pregunta | `not_actionable`, cero goals | dos formas interrogativas |
| orden ambigua | `needs_clarification`, cero goals | modalidad + alternativa |
| goal duplicado | `duplicate`, mismas IDs | request key + evento |
| goal bloqueado | `blocked` terminal | capacidad sin ejecutor |
| goal fallido | `failed` terminal | presupuesto agotado |
| goal expirado | `expired` terminal | política explícita |
| goal aprobado | `queued` con actor humano | evento `approved` |
| goal replanificado | `replanning → queued` | evento `replanned` |
| goal completado | `completed` terminal | cierre de root y paso |
| goal cancelado | `cancelled` terminal | root, paso y actor auditados |

## Archivos y migraciones

- `triade/core/capability_resolver.py`;
- `triade/core/planning_graph.py`;
- `triade/core/goal_orchestrator.py`;
- `apps/routes/api.py`;
- `triade/memory/schemas.sql`;
- `triade/memory/migrations/033_goal_lifecycle.sql`;
- `scripts/run_phase_3_goal_audit.py`;
- `tests/test_goals_end_to_end_real.py`;
- `artifacts/evolution/phase_3_results.json`.

La migración sólo crea `goal_events`, `goal_learning_observations` e índices.
No altera ni borra tablas existentes.

## Pruebas y resultados

- suite específica: todos los casos aprobados;
- compatibilidad del resolver, autonomía, dispatcher y estados de tareas:
  aprobada;
- ejecución real del diagnóstico: completada en aproximadamente 3 segundos;
- los gates globales y el total definitivo se registran en el PR de la fase.

## Comparación antes/después

| Medida | Antes | Después |
|---|---:|---:|
| roots históricos en limbo observados | 2 | 0 |
| filas históricas borradas | 0 | 0 |
| estados aceptados sin contrato | ilimitados | 11 enumerados |
| transiciones auditadas | 0 | 100 % de las nuevas transiciones |
| deduplicación de goals activos | no | sí |
| preguntas que abren goal en la suite | posible históricamente | 0 |
| terminales reabribles | sí, por actualización libre | no |

## Regresiones y riesgos

- Riesgo: consumidores históricos de `update_status()` pueden intentar una
  transición inválida. Mitigación: método compatible conservado, ahora fail
  closed, y suite global obligatoria.
- Riesgo: el clasificador determinista no comprende todo el lenguaje natural.
  Mitigación: ante modalidad o alternativas dudosas devuelve aclaración, nunca
  ejecución.
- Riesgo: una clave normalizada sólo deduplica la misma fuente textual, no
  equivalencia semántica. Se evita una deduplicación semántica agresiva que
  podría unir órdenes distintas.
- Riesgo: `blocked` es terminal. Una nueva intención debe abrir un nuevo goal
  trazable; no se reescribe el expediente cerrado.

## Rollback

1. Revertir los commits de la rama.
2. Las tablas aditivas pueden permanecer sin consumidores; no interfieren con
   el esquema anterior.
3. Para las cuatro filas runtime, ejecutar las sentencias `rollback_sql` del
   artefacto y borrar únicamente los eventos cuyo actor sea
   `phase3:goal-limbo-policy`.

## Deuda restante

- La calidad semántica avanzada del intent resolver sigue pendiente; esta fase
  sólo demuestra una clasificación conservadora y reproducible.
- El ciclo de workers completo, incluidos lease vencido, crash, dead letter y
  rollback, pertenece a la Fase 4.
- Una observación de goal no es aprendizaje consolidado. La Fase 1 sigue siendo
  la única demostración de aprendizaje con baseline, generalización y mejora.

## Criterio de cierre y recomendación

El cierre exige: todos los casos en estado válido, cero limbo sin política, cero
duplicados sin deduplicación y cero preguntas convertidas en ejecución. La
recomendación sólo será `merge` si la suite específica y todos los gates
globales terminan sin regresiones en el SHA final del PR.

# Los 8 task types que nunca se han ejecutado

Fecha: 2026-08-08 · Fase 5 del [plan de deuda](DEBT_TRIAGE_PLAN.md).

Para cada tipo hay que demostrar la cadena
`PRODUCTOR → COLA → LEASE → HANDLER → EFECTO → EVIDENCIA → COMPLETION`
y decidir si no haber corrido nunca es normal o es un corte.

**Los 8 tienen handler.** `TASK_HANDLERS` los mapea todos y `worker_loop` los
despacha. Ninguno es un tipo declarado sin implementar. La diferencia está
siempre en el productor o en su condición.

| task type | clase | por qué |
|---|---|---|
| `stable_consolidation_review` | **POLICY_BLOCKED** | poblaciones disjuntas (abajo) |
| `self_improvement_canary_observation` | **INCOMPLETE_SUBSYSTEM** | su tabla no existe en la base viva |
| `self_improvement_evaluation` | **INCOMPLETE_SUBSYSTEM** | su tabla no existe en la base viva |
| `bodega_global_review` | **PRODUCER_BROKEN** | su único productor es un fallback que no corre |
| `federation_inbox_review` | NO_TRIGGER_YET | espera un intercambio federado que no ha ocurrido |
| `goal_install` | NO_TRIGGER_YET | requiere petición de capacidad + aprobación humana |
| `goal_lora_train` | NO_TRIGGER_YET | requiere petición de capacidad + aprobación humana |
| `write_governed_text_artifact` | NO_TRIGGER_YET | requiere que el resolutor resuelva esa capacidad |

---

## `stable_consolidation_review` — el hallazgo del bloque

No es ausencia de estímulo. Es que el estímulo existe y está en el sitio
equivocado.

La condición del planner (`mission_planner.py:690`) es:

```sql
status IN ('validated_in_runs','evidence_verified')
  AND run_use_count >= 3
  AND avg_outcome_score >= 0.7
```

Y esto es lo que hay en `learning_queue`:

| estado | total | con uso | max usos | max score |
|---|---|---|---|---|
| `internally_checked` | 712 | **19** | 44 | 0.936 |
| `evidence_verified` | 10 | **0** | 0 | 0.0 |

Las dos poblaciones son **disjuntas**. Los candidatos que acumulan uso real
—hasta 44 usos con 0.93 de score— están en `internally_checked`, que la
condición no mira; y los 10 que sí tienen el estado exigido no se han usado
nunca. **16 candidatos ya cumplen `usos>=3` y `score>=0.7`** y no consolidan
sólo porque su estado no entra en la consulta.

Es la misma forma que el livelock de evidencia que se cerró en su día: medidos y
usados eran poblaciones distintas. Ha reaparecido un escalón más arriba, entre
`internally_checked` y `evidence_verified`.

La pregunta abierta, que no se resuelve tocando el planner: **qué promueve
`internally_checked → evidence_verified`, y por qué no elige a los que se usan.**
Bajar el umbral o añadir `internally_checked` a la consulta consolidaría
aprendizaje sin verificar, que es justo lo que la política quiere evitar.

## `self_improvement_*` — subsistema sin terminar

`_plan_self_improvement` comprueba `sqlite_master` antes de consultar, así que
no falla: simplemente no planifica nada. Las tablas `improvement_proposals` e
`improvement_canaries` **no existen en la base viva**, aunque el código que las
crearía está en `triade/self_improvement/{store,bridge,canary}.py`.

No es un corte de conexión: es una capacidad cuyo circuito nunca se cerró.
Nada que reparar en la cola; la decisión es si el subsistema se termina o se
archiva.

## `bodega_global_review` — productor inalcanzable

Es el único de los ocho sin productor real.

No aparece en `MissionPlanner`. Sus menciones son: el mapa de handlers, la lista
`READ_ONLY_TASKS_WITHOUT_BLOOD`, y `AdvancedScheduler.TASK_TYPES` —otro
planificador, cuya superficie viva se sirve desde `apps/routes/api.py`—.

Su única vía de encolado es `WorkerTaskQueue.enqueue_defaults()`, que encola
*todos* los tipos. Y eso es el **fallback** de `WorkerScheduler.schedule_cycle`:
sólo corre si `plan_cycle()` devuelve vacío o lanza, y `plan_cycle()` nunca
devuelve vacío. El productor existe en el código y el runtime no lo alcanza
jamás.

## Los cuatro `NO_TRIGGER_YET`

Ausencia legítima de estímulo, del mismo tipo que ya se documentó para el
eslabón `plan` de la cadena vital.

- `federation_inbox_review` espera `federated_exchange_log > 0`; la tabla tiene
  **0 filas**: no ha habido ningún intercambio federado.
- `goal_install` y `goal_lora_train` los produce `GoalOrchestrator` sólo tras
  aprobación humana explícita (`approve_install`, `schedule_lora`). Que no hayan
  corrido significa que nadie ha aprobado una instalación ni un entrenamiento.
- `write_governed_text_artifact` lo produce `GoalOrchestrator` cuando
  `CapabilityResolver` resuelve esa capacidad concreta.

Ninguno es deuda. Forzarlos exigiría fabricar el estímulo, que es justo lo que
no se hace.

---

## Qué queda abierto

1. Quién promueve `internally_checked → evidence_verified` y por qué no elige a
   los candidatos con uso medido. **16 candidatos esperando.**
2. Si el subsistema `self_improvement` se termina —creando sus tablas por la vía
   normal— o se archiva.
3. Si `bodega_global_review` debe tener productor en `MissionPlanner` o retirarse
   del contrato.

Ninguna de las tres se arregla en la cola de tareas: el contador de
`task_types_never_executed` es un síntoma, no la enfermedad.

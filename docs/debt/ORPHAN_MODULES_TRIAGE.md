# Triaje de los 3 módulos sin importador

Fecha: 2026-08-07 · Fase 4 del [plan de deuda](DEBT_TRIAGE_PLAN.md).

## Verificación común

La misma que exige el precedente `93496c8` («borrar 31 módulos sin importador,
con backup y verificación»), incluida su lección F-032: no fiarse del `grep`
sin abrir las líneas.

- **Carga dinámica**: el repositorio no la usa. Los `__import__` que existen son
  `__import__("datetime")` en `resource_probe.py` y una cadena en la lista de
  denegación de `safety.py`.
- **Imports**: cero para los tres, absolutos y relativos.
- **Tests**: ninguno importa ninguno.
- **Configs, workflows, TOML, Procfile, Dockerfile**: cero.

`matrix` dio 3 imports y 12 citas en configs, y **las 15 son falsos positivos**:
los imports apuntan a `triade.models.compatibility_matrix` —otro módulo, que sí
está vivo— y las citas son bloques `matrix:` de estrategia de GitHub Actions.
Es exactamente la trampa de F-032.

---

## `triade/core/plan_step.py` → **REMOVE**

Sustituido y nunca retirado.

Hay **dos** clases `PlanStep`. La de `triade/core/central.py:80` la usa todo el
mundo: `GovernedPlanDispatcher` y seis ficheros de test la importan. La de este
módulo no la importa nadie, ni un test.

La viva es estrictamente más rica: campo `state` con máquina de estados,
`StepBudget`, `rollback()`, `block()`, `can_retry()` y su propio `to_dict()`.
La huérfana usa `status`, y lo único que tiene en exclusiva son los conjuntos
`STEP_TYPES` y `STEP_STATUSES`, que no consume nadie y que no duplican ningún
vocabulario existente.

La historia lo cierra: `ebd2e9c` («feat(T-003): Central 2.0 — PlanStep
estructurado + Budget + Rollback») creó `core/plan_step.py` **y**
`core/plan_budget.py`; después `17ffa28` reescribió los módulos core metiendo
`PlanStep` dentro de `central.py`. Su hermano `plan_budget.py` ya se retiró en
`93496c8`. Este se quedó.

Recuperación: historial de Git.

## `triade/core/hierarchical_pulse.py` → **decisión del operador**

No es un duplicado, y por eso no se propone borrarlo sin más.

`HierarchicalPulseEngine` ofrece lo que `LifePulseEngine` **no** tiene:
`compute_interoception()`, `adaptive_interval()`, `hierarchical_reading()` y
lecturas por neurona y por worker. La API de `LifePulseEngine` no incluye
ninguna de esas.

Pero nunca ha corrido: la tabla que crea, `pulse_log`, **no existe en la base
viva**. Es una evolución escrita y no adoptada, no una alternativa abandonada.

Conectarlo no es gratis: sería un segundo motor de pulso latiendo sobre la misma
base junto a `LIFE_PULSE`, el mismo riesgo que documenta `triade_daemon.py` en
[`MANUAL_TOOLS.md`](../scripts/MANUAL_TOOLS.md). Así que la decisión es entre
**CONNECT** con diseño explícito —quién late, con qué cadencia y quién manda— y
**ARCHIVE**. No se toca hasta que esa decisión exista.

## `triade/capabilities/matrix.py` → **retenido, atado a la Fase 6**

`CapabilityMatrix.build()` lee `capability_registry`, que tiene **0 filas**.

No es código muerto por diseño: es el **consumidor que le falta** a una tabla que
nadie ha llenado. Su escritor —`triade/capabilities/registry.py`, líneas 107 y
163— es alcanzable desde un entrypoint (medido en Fase 2). O sea: la capacidad
está escrita de punta a punta y el evento que la llenaría no ha ocurrido nunca.

Conectarlo hoy devolvería una matriz vacía, que es peor que no tenerla: parece
una respuesta. La pregunta real —por qué `capability_registry` sigue en cero— es
la de la Fase 6, y este módulo se decide con ella, no antes.

---

## Resumen

| módulo | veredicto | por qué |
|---|---|---|
| `core/plan_step.py` | REMOVE | sustituido por `central.py:PlanStep`; hermano ya retirado; cero referencias |
| `core/hierarchical_pulse.py` | decisión pendiente | capacidad real no adoptada; conectarla duplica el pulso |
| `capabilities/matrix.py` | retenido | consumidor de `capability_registry`, vacía; se decide en Fase 6 |

El contador no baja en esta fase, y es correcto que no baje: dos de los tres no
son deuda que se resuelva borrando, y el tercero espera autorización.

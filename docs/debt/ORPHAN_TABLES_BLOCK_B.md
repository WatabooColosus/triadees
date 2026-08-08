# Bloque B — las 9 tablas sin lector ni escritor

Fecha: 2026-08-08 · `main` en `0254b28` · bloque B del [plan de deuda](DEBT_TRIAGE_PLAN.md).

Las nueve tienen **0 filas** y están declaradas en el esquema del repositorio.
Ninguna se creó por accidente: todas nacieron de una migración o de
`schemas.sql`. Lo que ninguna tiene es código que las use.

| tabla | definida en | menciones en código | veredicto |
|---|---|---|---|
| `benchmark_results` | `schemas.sql` | sólo un comentario | RETIRE *(pendiente historia)* |
| `benchmark_tasks` | `schemas.sql` | sólo un comentario | RETIRE *(pendiente historia)* |
| `federated_merge_log` | `schemas.sql` | sólo un comentario | RETIRE *(pendiente historia)* |
| `federated_merge_nodes` | `schemas.sql` | ninguna | RETIRE *(pendiente historia)* |
| `meta_model_candidates` | `schemas.sql` | ninguna | RETIRE *(pendiente historia)* |
| `meta_model_decisions` | `schemas.sql` | ninguna | RETIRE *(pendiente historia)* |
| `meta_model_evaluations` | `schemas.sql` | ninguna | RETIRE *(pendiente historia)* |
| `metabolic_config` | `032_metabolic_core.sql` | ninguna | **MERGE — sustituida** |
| `user_sessions` | `schemas.sql` | ninguna | RETIRE *(pendiente historia)* |

---

## `metabolic_config` — sustituida, con evidencia

El único caso con veredicto cerrado.

La migración `032_metabolic_core.sql:62` la crea como almacén clave/valor para la
configuración del metabolismo. Pero `MetabolicCoordinator.load_config()`
(`coordinator.py:141`) lee de **fichero**, con
`triade.core.config.load_config` — es decir, de `triade.yml`.

La configuración del metabolismo vive y funciona; lo que no se adoptó fue
guardarla en base. La tabla es el resto de una decisión que se tomó en el otro
sentido, y el subsistema que iba a usarla está sano sin ella.

**MERGE/RETIRE**: no hay nada que migrar —la información ya vive en `triade.yml`,
que es la fuente— así que la acción es retirar el esquema.

## `benchmark_*` y `federated_merge_log` — degradación ya documentada

Su única mención en todo el código es un comentario en `introspection.py:187`
que las nombra para explicar por qué existe la categoría
`tables_without_reader_or_writer`:

> `benchmark_results`, `benchmark_tasks` y `federated_merge_log` salieron del
> recuento el 2026-08-03 al quedarse sin escritor, sin haber ganado una sola
> fila: salieron por degradación (F-034).

O sea: el repositorio ya sabe que perdieron su escritor y **creó esta categoría
precisamente para que no desaparecieran del contador al quedarse huérfanas**. Son
el caso de uso que motivó la categoría, no una sorpresa.

## La historia, hecha el 2026-08-08 — veredictos cerrados

`git log -S` por tabla sobre `triade/`, `apps/` y `scripts/` contesta las tres
preguntas de golpe, y las tres apuntan al mismo sitio.

**1 · ¿Tuvieron escritor alguna vez?** Sí. Todas nacen en `ecc7d87`, un único
commit que introdujo a la vez «multi-user isolation, planning graph, federated
merge, autonomous sandbox, governed datasets, external evaluator, **meta model
orchestrator**, reasoning chains, hypothalamus pattern learning». No son esquema
adelantado a una implementación: la implementación existió.

Eso descarta `FUTURE_SCHEMA` para las ocho.

**2 · ¿Cómo perdieron el escritor?** Seis de las ocho aparecen en `93496c8`
—«borrar 31 módulos sin importador, con backup y verificación»—, y
`federated_merge_nodes` además en `8274ded` («remove dead code»). Es decir: sus
escritores eran módulos **que nadie importaba**, y cayeron en la limpieza
auditada de dead code, no por daño colateral. La tabla es el resto que esa
limpieza no barrió, porque borraba módulos y no esquema.

**3 · ¿Existe equivalente moderno?** Para `meta_model_*`, sí: la selección de
modelo la hace hoy `ModelRouter`, vivo y en uso. La función sobrevivió al
orquestador que la implementaba. No hay nada que migrar —las tablas nunca
tuvieron una fila— así que es supersesión, no `MERGE` con trasvase.

### Veredicto

**RETIRE las ocho.** Esquema huérfano de una implementación retirada con
auditoría, sin una sola fila en toda su historia y sin capacidad viva que
dependa de él.

### Lo que no hago

Ejecutar la retirada. Es una migración sobre la base de producción, y en este
repositorio eso lleva autorización explícita del operador —el mismo criterio con
el que se retiraron `plan_step.py` y `hierarchical_pulse.py`—. La acción, cuando
se autorice, es una migración `DROP TABLE` de las ocho más quitarlas de
`schemas.sql`, con la copia cifrada previa que ya se hace sola cada media hora.

`metabolic_config` va en el mismo lote, con su propio motivo: sustituida por
configuración en fichero.

## Anexo · el método que se siguió

El veredicto `RETIRE` de las siete restantes es **provisional**. Falta el paso
que el propio encargo exige y que no se puede saltar: la historia.

```bash
git log --oneline --all -S 'benchmark_results' -- triade/ apps/
```

por cada tabla, para responder tres preguntas que el estado actual no contesta:

1. ¿tuvieron escritor alguna vez, o el esquema se adelantó a una implementación
   que nunca llegó? Son dos veredictos distintos: `RETIRE` en el primer caso,
   `FUTURE_SCHEMA` en el segundo.
2. ¿el escritor se retiró a propósito o por daño colateral de otra limpieza?
   `93496c8` borró 31 módulos sin importador; conviene comprobar si alguno era el
   escritor de estas tablas.
3. ¿existe un equivalente moderno? `meta_model_*` suena a selección de modelo, y
   eso hoy lo hace `ModelRouter` — si su función vive ahí, es `MERGE`, no
   `RETIRE`.

**No se retira ningún esquema sin esas tres respuestas.** Una tabla vacía no hace
daño; borrar la única pista de una capacidad a medio construir, sí.

## Nota sobre el contador

Ninguna acción de código en este ciclo, así que la deuda no baja. Las nueve pasan
de «sin investigar» a «con evidencia y veredicto provisional», y una —
`metabolic_config`— queda con veredicto cerrado y lista para retirar.

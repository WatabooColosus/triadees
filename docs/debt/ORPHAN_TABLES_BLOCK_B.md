# Bloque B — las 9 tablas sin lector ni escritor

Fecha: 2026-08-08 · `main` en `0254b28` · bloque B del [plan de deuda](DEBT_TRIAGE_PLAN.md).

Las nueve tienen **0 filas** y están declaradas en el esquema del repositorio.
Ninguna se creó por accidente: todas nacieron de una migración o de
`schemas.sql`. Lo que ninguna tiene es código que las use.

| tabla | definida en | menciones en código | veredicto |
|---|---|---|---|
| `benchmark_results` | `schemas.sql` | sólo un comentario | KEEP_WITH_REASON *(corregido)* |
| `benchmark_tasks` | `schemas.sql` | sólo un comentario | KEEP_WITH_REASON *(corregido)* |
| `federated_merge_log` | `schemas.sql` | sólo un comentario | KEEP_WITH_REASON *(corregido)* |
| `federated_merge_nodes` | `schemas.sql` | ninguna | KEEP_WITH_REASON *(corregido)* |
| `meta_model_candidates` | `schemas.sql` | ninguna | KEEP_WITH_REASON *(corregido)* |
| `meta_model_decisions` | `schemas.sql` | ninguna | KEEP_WITH_REASON *(corregido)* |
| `meta_model_evaluations` | `schemas.sql` | ninguna | KEEP_WITH_REASON *(corregido)* |
| `metabolic_config` | `032_metabolic_core.sql` | ninguna | **KEEP_WITH_REASON** *(corregido)* |
| `user_sessions` | `schemas.sql` | ninguna | KEEP_WITH_REASON *(corregido)* |

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

**RETIRE las ocho** — *corregido el 2026-08-08: ver «Corrección» al final.
El veredicto real es `KEEP_WITH_REASON`.*

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

---

## Corrección (2026-08-08): el veredicto `RETIRE` era erróneo

**Veredicto real: `KEEP_WITH_REASON` las nueve.** Se intentó retirarlas cinco
veces y las cinco rompieron el runtime. Lo que sigue son los hechos medidos, no
una interpretación.

### Lo que se observó

**No hay excepción.** Con las tablas ausentes, el lifespan completa y reporta
`status: started`; `workers-always-on/status` da `active: true`,
`thread_alive: true`, `lock_file_active: true`, `last_error: null`. No hay
traceback en el log ni `no such table` en ninguna parte. El daño es silencioso.

**El síntoma es estable, no un arranque lento.** Tres minutos después de un
reinicio con las tablas realmente ausentes, el metabolismo sigue en
`running: False, mode: observe_only, cycle_count: 0`. La certificación falla en
`test_full_runtime_metabolism_is_running` y en los órganos.

**Restaurar sólo `metabolic_config` no bastó.** El metabolismo siguió en
`observe_only`. Hizo falta restaurar las 120 tablas para recuperar
`running: True, mode: full`. Así que no está demostrado que la dependencia sea de
una tabla concreta.

### Por qué los dos bisects dieron nueve «OK» falsos

Los dieciocho resultados que produjeron **no medían nada**, por la misma razón y
por dos vías distintas:

1. El primero hacía `DROP` en la base y reiniciaba, pero `schemas.sql` conservaba
   los `CREATE TABLE`: el arranque las recreaba antes de certificar.
2. El segundo también las quitaba de `schemas.sql` — y aun así
   `metabolic_config` volvía, porque la recrea la migración
   `032_metabolic_core.sql` en cada arranque.

En ambos casos el tratamiento se deshacía solo antes de la medición. Es la misma
forma del control contaminado que este repositorio ya documenta en su detector de
sondas, cometida aquí en el instrumento de medida.

La única certificación verde que se obtuvo con «las nueve retiradas» fue con
`metabolic_config` recreada por `032` sin que se advirtiera.

### Qué queda sin saberse

Por qué el organismo las necesita. Ninguna tiene lector ni escritor en el
análisis estático, ninguna tuvo jamás una fila, y su ausencia no produce error —
sólo un metabolismo degradado a `observe_only`. La vía por la que influyen no la
ven el grafo de tablas, ni `grep`, ni la historia de git.

Investigar eso exige instrumentar el arranque —registrar qué consulta el
coordinador del metabolismo antes de decidir su modo— y no adivinarlo. Hasta
entonces **no se retira ninguna**.

### Lección de método

Un bisect cuyo tratamiento se revierte solo produce confianza en vez de
conocimiento. Antes de dar por buena una retirada hay que comprobar que la cosa
retirada **sigue ausente** en el momento de medir, no sólo que se retiró.

---

## Segunda corrección (2026-08-08): las tablas tampoco eran la causa

La sección anterior afirma que «el organismo las necesita». **Es falso**, y queda
desmentido por una prueba aislada.

Sobre una **copia** de la base de producción con las nueve tablas borradas, se
instanció el coordinador del metabolismo directamente:

```text
config_path: triade.yml
metabolism del yml: {'enabled': True, 'mode': 'full'}
start(): running: True, status: started, thread_alive: True
```

Carga la configuración y arranca en modo `full` **sin ninguna de las nueve**. La
dependencia no existe.

### Lo que eso deja en pie

El síntoma en producción era real y reproducible —metabolismo en `observe_only`,
estable a los tres minutos—, pero su causa **no es el esquema**. Y hay una pista
concreta: `load_config()` devuelve `observe_only` únicamente cuando
`yml.get("metabolism")` sale vacío, es decir, cuando **no se pudo leer
`triade.yml`**. `config_path` es una ruta relativa.

Así que la hipótesis a comprobar es de arranque, no de base: qué directorio de
trabajo o qué orden de inicialización deja al coordinador sin poder leer su
fichero de configuración cuando se reinicia dentro de una secuencia de
operaciones sobre el esquema.

### Estado del veredicto

`KEEP_WITH_REASON` **se mantiene, pero por otro motivo**: no porque las tablas
hagan falta, sino porque el procedimiento de retirada dispara una regresión cuya
causa sigue sin identificarse. Retirarlas sigue sin ser seguro *tal como se ha
intentado*. Lo que ya no se sostiene es la explicación.

Tres veredictos seguidos erróneos en este bloque —`RETIRE`, luego
`KEEP_WITH_REASON` por dependencia, ahora esto— son razón suficiente para no
volver a tocarlo sin instrumentar antes el arranque.

---

## Tercera corrección: por qué ningún experimento aislado valía

Instrumentar el arranque —ejecutar la secuencia exacta del lifespan en vez de
construir el coordinador a mano— revela dos cosas que invalidan todo lo anterior.

```text
db_path del singleton: triade/memory/triade.db   ← ignora TRIADE_DB_PATH
config_path: triade.yml
load_config -> {'enabled': True, 'mode': 'full'}
start() -> {'status': 'locked', 'error': 'another_process_holds_lock'}
```

**1 · `get_coordinator()` ignora `TRIADE_DB_PATH`.** Usa la ruta por defecto
codificada. La «prueba sobre una copia con las nueve tablas borradas» que dio
verde nunca tocó la copia: leía la base real, con las tablas presentes. El
experimento que supuestamente demostraba que las tablas no hacen falta **no
probaba nada**, igual que los dos bisects anteriores.

**2 · `start()` devuelve `locked` con el runtime vivo.** Ninguna prueba en
proceso reproduce el arranque real mientras el servicio corre.

### La hipótesis que queda, y cómo comprobarla

El endpoint de estado reporta `enabled: False, mode: observe_only` — que son los
**valores por defecto del constructor**, no los de `triade.yml`. Eso ocurre si
`load_config()` nunca llega a ejecutarse.

En el lifespan la secuencia es `get_coordinator()` → `load_config()` →
`start()`, dentro de un `try` que captura `sqlite3.Error` entre otras y guarda el
fallo en `metabolism_result`. Si `get_coordinator()` toca en su construcción
alguna de las nueve tablas, lanza, `load_config()` no corre, el coordinador
conserva sus defaults y **el error queda escrito en un sitio que nadie lee**:
`_ALWAYS_ON_RESULT["metabolism"]`, que `/health/deep` no expone —sólo publica
`status`, `conversation_only` y `background_started`—.

Comprobarlo es exponer ese campo. Es además una mejora por sí sola: hoy el
metabolismo puede fallar al arrancar y el sistema reporta `status: started` sin
que el error sea visible por ninguna superficie.

### Estado

Seis intentos de retirada, cuatro veredictos equivocados. El bloque queda
**abierto y sin retirar**, y la deuda en 57. Lo aprendido vale más que las nueve
tablas: tres instrumentos de medida distintos —bisect, copia aislada,
construcción directa— daban verde sin medir lo que decían medir.

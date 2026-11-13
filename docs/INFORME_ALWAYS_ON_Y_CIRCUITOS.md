# Always-On real y cierre de circuitos cognitivos

**Base:** `main` en `dfa3da4` (incluye el PR #103, fusionado al empezar).
**Rama:** `fix/always-on-and-close-cognitive-loops`.
**Fecha:** 2026-08-10 / 2026-08-11 UTC.

---

## 1. El diagnóstico: por qué Tríade no sobrevivía a un reinicio

No era falta de supervisor. Era que **el supervisor no existía cuando arrancaba
la máquina**.

La raíz de este Studio es un overlay de contenedor: sólo persiste
`/teamspace/studios/this_studio`, y `/etc/systemd/system` se recrea vacío en
cada arranque. Las units estaban escritas en el repo y nadie las instalaba, así
que la cabecera de `on_start.sh` —«las units ya arrancan solas por boot porque
están enabled»— describía algo que no ocurría.

Medido el 2026-08-10 con el Studio 19 minutos arriba:

| Señal | Valor |
|---|---|
| units `triade*` instaladas | **0** |
| listeners en :8010 | **0** |
| `studio-web.log` | última línea, la parada limpia de la sesión anterior (05:30) |
| Ollama | vivo, pero en `/workload.slice`: huérfano sin supervisor |

Encima había **tres** mecanismos de arranque compitiendo:

1. `on_start.sh`, que esperaba systemd y caía a `nohup`;
2. `triade_runtime.sh`, que lanzaba uvicorn con `setsid nohup` por su cuenta;
3. `post_reboot_verify.sh`, que se anunciaba como «safe, non-destructive» y
   arrancaba Ollama y la API con `nohup` en sus pasos 2 y 4.

El tercero es el que más daño hacía, porque `on_start.sh` lo llamaba en segundo
plano justo después de pedirle a systemd lo mismo.

## 2. La reparación

Una sola cadena, un solo supervisor:

```
BOOT → on_start.sh (shim) → deploy/lightning_studio/on_start.sh
        ├─ restore_file_modes.sh
        ├─ install_systemd_units.sh   ← instala y habilita desde el repo
        └─ systemctl start …
             ├─ triade-ollama.service
             ├─ triade-api.service    → :8010 (workers dentro del proceso)
             ├─ triade-watchdog.service
             └─ triade-backup.timer
```

Cambios de fondo:

- **Las units se reinstalan en cada arranque** desde `deploy/systemd/`, porque
  `/etc` no persiste. Idempotente.
- **`triade_runtime.sh` pasa a ser cliente de systemd**, no dueño. El arranque
  productivo es el mismo lo pida una persona o lo pida el boot.
- **`post_reboot_verify.sh` deja de lanzar procesos**: si algo falta, se lo pide
  a systemd.
- **Se retira `triade-workers.service`**: los workers ya corren dentro del
  proceso de la API, y una unit aparte sería un segundo pool sobre la misma base.
- **Las units leían `EnvironmentFile=/etc/triade/triade.env`**, que tampoco
  persiste y no existía: sin el guion inicial, systemd habría rechazado la unit.
  Ahora leen el `.env` del repo.
- **Reinicio gobernado**: `StartLimitIntervalSec=300` + `StartLimitBurst=5`. Al
  sexto arranque en cinco minutos la unit queda en `failed` en vez de tormentear.
- **Ollama no tumba a Tríade**: `Wants=`, no `Requires=`.

### El fallo de los modos de fichero

El reinicio del Studio deja todo el árbol en `0744`. Con `core.fileMode=false`
git no lo ve y `git status` sale limpio, así que rompe tres cosas en silencio:

1. `ruff check .` pasa de 0 a **715 errores EXE002**;
2. la clave de backup deja de estar en `0600` y `EncryptedBackup` se niega a
   cifrar — estaba **otra vez en 744** en este arranque, o sea que las copias
   volvían a estar rotas;
3. la clave de firma de commits queda en `0744`, ssh la ignora por insegura y
   `git commit` **falla entero**.

`scripts/restore_file_modes.sh` los devuelve desde el índice de git, y entra en
el arranque antes que nada.

## 3. Certificación de Always-On

### Crash → recuperación (`scripts/certify_always_on.py`)

SIGKILL al proceso productivo, sin relanzar nada a mano:

| Medida | Valor |
|---|---|
| detección (puerto sin listener) | **0,66 s** |
| `/health/live` de vuelta | **26,02 s** |
| workers activos de nuevo | **33,49 s** |
| `NRestarts` | 1 → 2 (lo hizo systemd) |
| intervención manual | **ninguna** |

12 de 12 comprobaciones: reinicio por el gestor de servicios, un solo listener,
misma base, mismo historial, workers recuperados, **progreso posterior**
(ciclo 2 → 3), integridad `ok`, 0 violaciones de clave foránea.
**Veredicto: CERTIFIED.**

### Arranque en frío (`scripts/certify_cold_boot.sh`)

Reproduce la causa real sin reiniciar el host: borra las units como hace la
recreación del contenedor y ejecuta el mismo guion del boot.

7 de 7: units retiradas, vuelve **sin arranque manual en 30 s**, URL restaurada,
un solo listener, bajo systemd, autoarranque rehabilitado, workers recuperados.
**Veredicto: CERTIFIED.**

En el primer intento **falló** — y falló bien: todo salía verde menos
`service_managed`, porque el `nohup` de `post_reboot_verify.sh` ganó la carrera
y dejó el 8010 servido desde `/workload.slice` mientras `triade-api.service`
arrancaba su propio uvicorn por detrás. Preguntarle a systemd si la unit estaba
activa habría dicho que sí. Lo detectó la comprobación de cgroup.

### `HOST_REBOOT_TEST = NOT_EXECUTED`

Reiniciar la máquina desde dentro del entorno de trabajo destruiría la sesión.
No se finge la prueba: se certifica el equivalente del gestor de servicios y la
pérdida de `/etc`, que es la causa que mataba a Tríade.

## 4. El circuito cognitivo: tres aprendizajes independientes

A las **00:00:30 UTC** del 2026-08-11, al reiniciarse la cuota diaria del
gobernador (`deep_evaluations_daily` de 12/12 a 1/12), `stable_consolidation_review`
volvió a ser encolable y **un worker consolidó los tres candidatos que estaban
listos**, sin que se forzara nada:

| Candidato | Usos causales | Score | Documento stable |
|---|---|---|---|
| `exp-c50522e1125e4723` (ventana de mantenimiento) | 4 | 1.0 | `sem-64378483949b44ce` |
| `exp-6afda5f39b26430b` (identificador de entorno) | 3 | 1.0 | `sem-2f130119b3784051` |
| `exp-de6f666aca5a4aaa` (nombre en clave del informe) | 3 | 1.0 | `sem-a9d51f9d841d48a5` |

Los tres pasaron los dos gates: `candidate → experimental → stable`, firmados
por `worker-stable-review:worker-2026-08-10T234902…`. **Es la primera tanda
consolidada de forma autónoma**: la primera consolidación de la base, el
2026-08-09, llevaba `certificacion-fase8:forzado-por-operador`.

El bloqueo anterior era **legítimo** y se esperó a que expirara. No se tocó el
presupuesto ni se bajó ningún listón.

### RUN B: se recupera y se usa

`run-20260811-000255-196d8252` — pregunta que **no contiene la respuesta**
(«¿Cuál es mi ventana de mantenimiento acordada?»):

- respuesta: **`VENTANA_JUEVES_0300`**, exacta;
- gobernanza semántica `applied`, `allowed_statuses: ["stable"]`;
- **1 match admitido, 2 en cuarentena**.

Control `run-20260811-000513-a010da9a` («¿Cuántos planetas…?»): responde `8`,
**0 admitidos y 3 en cuarentena**.

Esto mejora el estado del 2026-08-09, donde la influencia semántica estaba
autorizada pero **no observada** en la conducta del modelo.

**Limitación que hay que decir:** el control **no está limpio a nivel de
contexto**. El dato aparece igualmente en su `memory_diff` por dos vías: el
canal por palabras clave admite el documento stable aunque la pregunta no venga
a cuento (sólo discriminó el canal vectorial), y `verified_candidates` guarda
transcripciones crudas de runs anteriores en vez de afirmaciones destiladas. La
causalidad del tratamiento se sostiene; la limpieza del control, no del todo.

## 5. Deuda real

| Momento | Hallazgos | De ellos, trabajo pendiente |
|---|---|---|
| baseline sobre `dfa3da4` | **40** | 38 |
| con el runtime en pie | 37 | 35 |
| tras arreglar el detector de copias | 36 | 34 |
| tras hacer que el triaje lea los contratos | **34** | **21** |

- `declared_services_not_running`: **3 → 0**. Se cerró ejecutando los servicios,
  no reclasificándolos.
- `backup_protection_gaps`: **1 → 0**. Era un **falso positivo**: el detector
  preguntaba por `os.getenv` del proceso que audita, y quien hace las copias es
  el runtime, que recibe su configuración del `.env` por `EnvironmentFile`. El
  proceso de la API tenía la variable; la auditoría desde la terminal declaraba
  «sin clave» igualmente. De paso, la comprobación de permisos del fichero de
  clave —la que encontró el `0744` que bloqueaba restaurar— nunca llegaba a
  ejecutarse.

Un falso positivo aquí es peor que no medir: esta categoría existe porque el
2026-07-31 la clave desapareció de verdad y nadie se enteró en cuatro días.

### El triaje no leía los contratos

El repositorio tenía **dos sistemas para lo mismo y no se hablaban**. Los
contratos de activación deciden y documentan, con evidencia, por qué una tabla
vacía o una tarea sin ejecutar es correcta; `scripts/triage_debt.py` los
ignoraba y volvía a etiquetar esos mismos sujetos como `incomplete_subsystem`.
`hardware_senses` y `evidence_remediation_audit` figuraban como subsistema
incompleto teniendo contrato `AUDIT_LEDGER` e `HISTORICAL` desde el 2026-08-08.

Contar dos veces no sólo infla la cifra: empuja a «arreglarla» inventándole un
lector a una bitácora de sólo escritura, y un lector falso no conecta nada —
hace parecer que hubo consumo.

Ahora el triaje reverifica cada contrato **contra el repositorio y la base viva
en cada medición**. De 34 hallazgos, **21 son trabajo pendiente real** y 11 son
decisiones ya tomadas cuya evidencia se sostiene.

Y la reverificación no sella. `self_improvement_evaluation` tiene contrato
`HUMAN_GATED`, pero su evidencia alegaba `rows_absent=improvement_proposals`;
como ahora hay una propuesta, la evidencia **dejó de sostenerse** y el sujeto
volvió a contar como deuda. `DEUDA_REAL` no excusa nunca: sería usar el sistema
de contratos para tapar lo único que declara no tener excusa.

## 6. Cómo se reproducen estas cifras

Las dos fotos —antes y después— salen del mismo código, para que una diferencia
en la tabla sea una diferencia real y no un cambio de criterio al contar:

```bash
python scripts/measure_state.py --out artifacts/always_on/state-before.json
# … cambios …
python scripts/measure_state.py --out artifacts/always_on/state-after.json
```

`scripts/measure_state.py` cuenta las etapas del circuito cognitivo, la cola de
muertos, lo que está en vuelo, la integridad y las claves foráneas, y adjunta el
bloque de supervisión. Dos cuidados que ya costaron un diagnóstico equivocado:
las ventanas de tiempo comparan con `strftime('%Y-%m-%dT…')` y no con
`datetime('now')` —las tablas guardan la 'T' y `datetime('now')` mete un espacio,
que como texto es menor y ensancha la ventana—, y lo que no se puede contar sale
como `null`, no como `0`.

El resto de comprobaciones:

```bash
python scripts/certify_always_on.py --wait 300      # crash -> recuperación
bash   scripts/certify_cold_boot.sh                 # pérdida de /etc -> arranque
python scripts/run_long_validation.py --hours 2 --interval 5 --label soak
python scripts/build_internal_graphs.py && python scripts/triage_debt.py
```

## 7. Lo que queda abierto, y por qué

- **Mejora / canary.** Ver §8: el circuito estaba muerto por construcción y ya
  no lo está, pero la señal viva no alcanza el umbral, así que la cadena queda
  legítimamente detenida en un rechazo gobernado.
- **`goals`.** Única retirada de esquema pendiente (0 filas, superada por
  `planning_graph`). El propio aplicador reserva la decisión al operador porque
  exige rebasar el ancla de identidad.
- **Federación.** `federated_nodes` 20, `federated_exchange_log` 0. Clasificado
  `NO_EXTERNAL_STIMULUS`: la cadena está construida y probada, falta un segundo
  nodo.
- **Destilación de afirmaciones.** La extracción sigue guardando transcripción
  cruda como candidato; se ve en la contaminación del control de la §4.

## 7b. Tres mentiras en voz baja

Las tres averías más caras de esta sesión son de la misma familia: **no fallan,
mienten**. Un lector vivo consulta una tabla que nunca tendrá filas, recibe el
caso vacío, y lo publica como si fuera la respuesta.

| Lector | Consultaba | Efecto real |
|---|---|---|
| `learning_journal` | `semantic_memory` (0 filas, 0 `INSERT` en el repo) | Reportaba **cero** actividad semántica la misma noche que se consolidaron 3 memorias estables. Se sirve en `/api/runtime/learning-journal`. |
| `EncryptedBackup._semantic_verification` | `semantic_memory` | El simulacro de restauración **no podía detectar** que se perdiera el saber: daba 0 tanto si se perdía como si no |
| `triage_debt` | nada — ignoraba los contratos | Recontaba 11 decisiones ya tomadas y documentadas como trabajo pendiente |

Los dos primeros ahora leen `semantic_documents`, que es donde el pipeline
escribe (379 filas). El diario pasó de `count: 0` a datos reales; la
verificación de copia, de 0 a 379.

### El patrón: escritores que sólo alcanzan los tests

Tres de las 21 deudas pendientes son el mismo caso, y merece nombre porque el
detector no lo distingue: la tabla tiene escritor declarado, el escritor está
escrito y probado, y **el único que lo llama en todo el repositorio es un test**.
En producción esa tabla no puede recibir una fila jamás.

| Tabla | Escritor | Único llamante | Lectores vivos |
|---|---|---|---|
| `auto_identity` | `AutoIdentityStore.add_or_update` | `tests/test_auto_identity.py` | `core/bodega.py`, `core/life_pulse.py` |
| `orchestrator_locks` | `OrchestratorCoordinator.try_acquire` | `tests/test_autonomy_foundations.py` | su propio `cleanup()`, que sí corre al arrancar |
| `sandbox_executions` | `AutonomousSandbox.execute_code` | ninguno (el worker sólo usa `create_snapshot`) | 7 |

El detector los agrupa en `tables_with_writer_and_no_rows` con el mensaje «la
ruta de escritura existe y no se ha ejecutado nunca», que es cierto pero no dice
lo importante: no es que esté ociosa, es que **nadie la ha conectado**.

Ninguno se conecta aquí, y por la misma razón en los tres: conectarlos son
decisiones de diseño, no reparaciones mecánicas. Cuándo se forma Tríade rasgos
sobre sí misma toca su identidad y su contexto; qué se ejecuta dentro del
sandbox toca la seguridad; qué se serializa con locks toca la concurrencia.

Se estuvo a punto de escribir un contrato `EXPECTED_EMPTY` para
`orchestrator_locks` —«tabla de locks transitorios, vacía en reposo es
correcto»—. Habría sido falso: no hay locks transitorios porque nunca se toma
ninguno. Verificar quién llama al escritor es lo que lo evitó.

### `auto_identity`: escritor sólo alcanzable desde los tests

Queda anotado y **sin tocar**, a propósito. `AutoIdentityStore.add_or_update` y
`evolve_from_reflection` no los llama ningún módulo de producción: los únicos
llamantes en todo el repositorio están en `tests/test_auto_identity.py`. La
tabla no puede recibir una fila fuera de los tests.

Mientras tanto sí hay lectores vivos: `core/bodega.py` la consulta para montar
el contexto y `core/life_pulse.py` cuenta sus rasgos. O sea, una capacidad que
se lee y nunca se escribe.

No se conecta aquí porque conectarla es decidir **cuándo se forma Tríade rasgos
sobre sí misma**, y eso entra en el contexto de sus respuestas y roza el ancla
de identidad. Es una decisión del operador, no una reparación mecánica.

## 8. Automejora: el circuito no podía empezar

`improvement_proposals`, `improvement_candidate_links`, `improvement_canaries`,
`improvement_canary_observations` y `neuron_candidates`: **todas a cero**. La
lectura cómoda era «nadie ha propuesto nada todavía». La real es peor y es un
fallo de circuito:

- `MissionPlanner._plan_self_improvement` sólo encolaba
  `self_improvement_evaluation` si ya había propuestas en `approved`;
- lo único capaz de aprobar sin humano —la política de auto-aprobación— vive
  **dentro** de ese mismo handler.

Una propuesta `open` no podía llegar a `approved` por sí sola. El código de
auto-aprobación era **inalcanzable** salvo que una persona aprobara antes a
mano, que es justo lo que la política venía a evitar. La cadena no estaba
esperando: no podía empezar.

Y cuando llegaba a ejecutarse, **no había listón**: aprobaba la primera
propuesta abierta que encontrara sin mirar la calidad de la señal que la origina.

### Lo reparado

- `triade/self_improvement/auto_approval.py` concentra la regla en un sitio, y
  la consultan **planificador y worker**. Que cada uno decidiera por su cuenta
  es cómo se llega a un planificador que encola trabajo que el worker rechaza.
- El planificador encola también cuando hay propuestas `open` **auto-aprobables**.
  No cuando hay propuestas abiertas cualesquiera: encolar una tarea que no va a
  poder hacer nada es el fallo contrario, girar en vacío.
- **Umbral de 0.94** sobre la confianza de la señal, autorizado por el
  responsable el 2026-08-11. Se mira la confianza y no el impacto: el impacto
  dice cuánto se ganaría si la hipótesis fuera cierta, la confianza dice cuánto
  sabemos que lo es. Un valor ilegible en el entorno no baja el listón.
- `requires_human_approval` **no** bloquea en este paso, a propósito. El gate
  duro ya está en `stable_promotion_gate` —experimental → estable, el paso
  irreversible—. Ponerlo también aquí devolvería el subsistema a cero
  justamente para el caso que existe en producción.

### Dónde queda ahora, y por qué está bien

La única señal viva (`conversational_learning` / `learning_recall`, observado
0.0 frente a 1.0) tiene **confianza 0.4**. Con el umbral en 0.94, la política
**no la aprueba**, y lo dice: `propuesta no auto-aprobable: confianza 0.40 por
debajo del umbral 0.94`.

Eso no es el circuito roto: es el circuito funcionando. Antes el subsistema
estaba a cero porque no podía arrancar; ahora está detenido porque una regla
explícita decidió que esa hipótesis no merece ejecutarse sola, y deja rastro.

`improvement_proposals` pasó de **0 a 1** por el camino: la propuesta se creó
por la API gobernada a partir de una señal que produjo la propia Tríade.

### Firma de las aprobaciones automáticas

El responsable autorizó que estas aprobaciones queden certificadas a su nombre.
Se estampa con `TRIADE_SELF_IMPROVEMENT_POLICY_AUTHORIZER` (vive en `.env`,
fuera de git, porque el `approved_by` acaba escrito en la base y en informes de
auditoría), y va **detrás del prefijo `auto:`**, no en su lugar:

```
auto:threshold_policy (autorizado por Wataboo Colossus)
```

El responsable eligió un identificador de organización y no datos personales,
que es lo correcto: este campo se escribe en la base y se publica en artefactos
de auditoría, y el historial de git no se borra.

La autorización es real y permanente; la decisión concreta la tomó la política.
Una firma humana indistinguible de una automática no protege a quien firma: le
atribuye decisiones que no miró.

## 8b. Lo que encontró el soak: conexiones SQLite que no se cierran

Es el hallazgo que justifica la ventana larga, y no habría salido en ninguna
prueba corta.

| hora | RSS | FDs |
|---|---|---|
| 23:50 | 306 MB | 99 |
| 00:00 | 499 MB | 129 |
| **00:05** | **9.384 MB** | **39.028** |
| 00:10 | 16.006 MB | 128 |
| 00:47 | 11.258 MB | 134 |

**Dos ejecuciones de `/api/run`** —el RUN B y su control— llevaron el proceso de
500 MB a un pico de **16 GB**, con **39.028 descriptores de fichero** abiertos a
la vez, y dejaron ~10,7 GB retenidos. Lleva 40 minutos plano en 11,25 GB, así
que no es una fuga sin freno; pero en una máquina de 31 GB, un puñado de
conversaciones agota la RAM.

### El mecanismo, demostrado

En reposo, **83 de los 118 descriptores del proceso son conexiones abiertas a
`triade.db`** (más 7 al WAL). El pico de 39.028 fueron ~39.000 conexiones SQLite
simultáneas, y como cada una reserva su propia caché de páginas
(`cache_size = -2000`, es decir 2 MB), eso explica los dos síntomas a la vez: los
descriptores **y** los gigabytes. La meseta en 11,25 GB es el asignador, que no
devuelve las arenas al sistema operativo después de liberarlas.

La causa es un malentendido muy extendido de Python:

```python
with sqlite3.connect(db) as conn:  # NO cierra la conexión
    ...
```

El gestor de contexto de `sqlite3` administra la **transacción**, no la vida de
la conexión. Comprobado en esta misma máquina: 50 bloques `with` con la
referencia retenida dejan **50 descriptores abiertos**; sólo `close()` los
libera.

Hay **285 llamadas a `sqlite3.connect` en código de producción**. Mientras la
referencia muera enseguida, el contador de referencias de CPython las cierra
solo; en cuanto una queda en una caché, un closure o un ciclo, la conexión —y
sus 2 MB— viven hasta que pase el recolector cíclico.

### Por qué no se arregla aquí

Repasar el ciclo de vida de 285 puntos de conexión es un trabajo con su propio
riesgo y sus propias pruebas, y hacerlo al final de una sesión larga, sobre un
runtime que hay que dejar en pie, es la forma de introducir una regresión en la
capa de persistencia. Queda diagnosticado, con reproducción y mecanismo, que es
lo que hace falta para atacarlo bien.

## 8c. Resultado del soak

Ventana abierta a las 23:50:17 UTC con muestreo cada 5 min. **16 muestras
válidas cubriendo 77 minutos continuos** (23:50:23 → 01:07:20 UTC).
El requisito del encargo eran 60 minutos; el ideal, 2 horas. Se cierra el
informe en esos 77 minutos: las muestras posteriores al primer commit quedan
marcadas `sha_changed` por el propio guion y no se cuentan.

| Medida | Resultado |
|---|---|
| uptime del proceso | **84 min** |
| reinicios no provocados | **0** |
| listeners en :8010 | **1**, todo el tiempo |
| tareas completadas | **345/hora** |
| dead letters nuevos | **0** |
| workers atascados | **0** |
| violaciones de clave foránea | **0** |
| `integrity_check` | `ok` |
| memoria | pico 16 GB, meseta estable en 11,25 GB (ver §8b) |

Durante la ventana, además: se consolidaron tres aprendizajes solos (§4) y el
proceso de Claude Code que orquestaba la sesión **se cayó y volvió**, mientras
Tríade seguía corriendo sin enterarse. No estaba planeado como prueba, pero es
la demostración más limpia de que el runtime ya no depende de que alguien tenga
una terminal abierta.

## 9. BEFORE / AFTER

| | BEFORE | AFTER |
|---|---|---|
| arranque manual necesario | **sí** | **no** |
| autostart | ninguno (0 units instaladas) | `enabled` (systemd, reinstaladas en cada boot) |
| listeners en :8010 | 0 | 1 |
| recuperación tras crash | no había | **26,0 s** hasta `/health/live`, 33,5 s hasta workers |
| misma DB tras reiniciar | sin comprobar | **sí**, ruta absoluta y contadores verificados |
| hallazgos de deuda | **40** | **34** |
| de ellos, trabajo pendiente real | 38 | **21** |
| `declared_services_not_running` | 3 | **0** |
| `backup_protection_gaps` | 1 (falso positivo) | **0** |
| violaciones de clave foránea | 0 | 0 |
| integridad SQLite | ok | ok |
| dead letters (total / 24 h) | 181 / 0 | 181 / 0 |
| workers atascados | 0 | 0 |
| `evidence_verified` | 18 | 16 |
| candidatos `consolidated` | 2 | **5** |
| documentos `stable` | 2 | **5** |
| aprendizajes independientes consolidados solos | 0 | **3** |
| usos causales confirmados | 407 | 407 + los del RUN B |
| `improvement_proposals` | 0 | **1** |
| ciclos de mejora completados | 0 | 0 (rechazo gobernado: confianza 0.40 < 0.94) |
| errores del frontend | build limpio | build limpio, tarjeta de supervisión añadida |

## 10. Matriz final

| Área | Estado | Evidencia |
|---|---|---|
| Always-On | **CERTIFIED** | 12/12 crash-restart + 7/7 arranque en frío; `always_on: true`, `manual_start_required: false` medidos |
| Runtime | **CERTIFIED** | soak con 0 reinicios no provocados, 1 listener, integridad `ok` |
| Workers | **FUNCTIONAL** | activos y recuperados tras SIGKILL; degradan a `cooldown` por load average, que es la política haciendo su trabajo |
| Scheduler | **FUNCTIONAL** | encoló y ejecutó `stable_consolidation_review` sola al liberarse la cuota |
| Model | **FUNCTIONAL** | Ollama bajo unit propia; la API sobrevive a su caída (`Wants=`) |
| Memory | **CERTIFIED** | misma base tras reinicio, 0 violaciones FK, `integrity_check` ok |
| Learning | **CERTIFIED** | 3 aprendizajes independientes LEARN→VERIFY→CONSOLIDATE→STABLE, consolidados por worker |
| Goals | **PARTIAL** | `planning_graph` con 30 nodos y 4 `completed`; la tabla `goals` está retirada y su migración sigue sin aplicar |
| Improvement | **PARTIAL** | circuito reparado y alcanzable; detenido en un rechazo gobernado por umbral, sin canary todavía |
| Neurons | **FUNCTIONAL** | 28 neuronas, 794 actividades, 106 eventos de educación; `neuron_candidates` a 0 porque cuelga del circuito de mejora |
| Federation | **BLOCKED** | `NO_EXTERNAL_STIMULUS`: cadena construida y probada, faltan peers (20 nodos declarados, 0 intercambios) |
| Safety | **FUNCTIONAL** | gobernanza semántica `applied`, cuarentena discriminando (1 admitido / 2 en cuarentena) |
| Observability | **CERTIFIED** | bloque `supervision` medido en `/health/deep` y en el dashboard |
| Frontend | **FUNCTIONAL** | build limpio, tarjeta de supervisión servida desde backend real; SYSTEM 3D causal **no** abordado |

### Lo que no se hizo

- **SYSTEM 3D causal** (§24 del encargo): no abordado. El grafo interno se
  regenera y se publica, pero no se convirtió en mapa causal
  `DEBT → NODE → PRODUCER → WRITER → READER → EFFECT`.
- **Prueba de reinicio del host**: `NOT_EXECUTED`, con razón explícita.
- **Retirada de `goals`**: requiere rebasar el ancla de identidad, y el propio
  aplicador reserva esa decisión al operador.
- **Ciclo de vida de las conexiones SQLite** (§8b): diagnosticado y no
  reparado. Es el siguiente trabajo, y el de mayor impacto operativo.
- **`auto_identity`**: escritor alcanzable sólo desde los tests. Conectarlo es
  una decisión de identidad del operador (§7b).

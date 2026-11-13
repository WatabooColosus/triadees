# Plan por fases para los 97 elementos de deuda

Fecha: 2026-08-07 · Medido con `build_debt_report(max_age_seconds=0)` sobre
`triade/memory/triade.db` y los grafos regenerados en el commit `d65d222`.

El objetivo no es 97 → 0. Es que cada elemento tenga una explicación
arquitectónica y de runtime demostrable, y que el grafo describa la Tríade real.

---

## 1 · Lo que cambia el mapa antes de empezar

Tres hechos verificados que reordenan la prioridad. Sin ellos, el plan atacaría
el contador en vez del sistema.

### 1.1 · El contador no son 97 problemas distintos

De los 97, **58 son sobre tablas** y mencionan **35 tablas distintas**: 23
elementos son el mismo hecho contado dos veces.

| par de categorías | elementos en común |
|---|---|
| `alias_debt_orphan_reader` ∩ `tables_with_writer_and_no_rows` | **19 de 20** |
| `alias_debt_lexical_alias` ∩ `tables_with_writer_and_no_rows` | 2 |
| `alias_debt_lexical_alias` ∩ `tables_without_reader_or_writer` | 2 |
| `alias_debt_lexical_alias` ∩ `alias_debt_orphan_reader` | 1 |

No es casualidad: las dos categorías grandes miden **la misma condición**. El
`detail` de cada hallazgo `orphan_reader` lo dice literalmente:

> `auto_identity` tiene 2 lector(es), 1 escritor(es) y **0 filas**: el escritor
> existe y no se ejecuta nunca

Que es la definición de `tables_with_writer_and_no_rows`. Sólo difieren en un
elemento por lado (`runtime_queue_compatibility_events` / `neuron_certifications`).

### 1.2 · El «gemelo vivo» es una conjetura por parecido de nombre

El campo `live` de cada `orphan_reader` sale de `closest_live_table` por
similitud de cadena, no de evidencia:

| tabla muerta | «gemelo» propuesto | similitud |
|---|---|---|
| `auto_identity` | `identity_core` | 0.43 |
| `capability_history` | `scheduler_history` | 0.49 |
| `goal_dependencies` | `goal_events` | 0.44 |
| `federated_exchange_log` | `federated_nodes` | 0.28 |
| `capability_registry` | *(ninguno)* | 0.00 |

`capability_history` → `scheduler_history` con 0.49 son dominios distintos.
**Migrar un lector guiándose por este campo escribiría en la tabla equivocada.**

Además, los 20 hallazgos traen `runtime_verified: False` y `reachable_writer:
None`. El dataclass tiene el hueco para evidencia de ejecución
(`alias_debt.py:152-154`) y **nunca se rellena**: hoy todo el bloque de tablas
es análisis estático puro.

### 1.3 · El panel va por detrás del proceso vivo

El panel mostraba `vital chain gaps — 1` cuando con el código de `main` ya vale
**0**: sirve lo que tiene cargado el proceso, que se reinició antes del merge.
Igual con `backup protection gaps`, que da 1 o 2 según el entorno desde el que
se mida (`TRIADE_BACKUP_KEY_FILE` vive en `.env`).

**Regla operativa: tras integrar en `main`, reiniciar el runtime antes de leer
el panel.** Un panel y un `main` que no coinciden producen trabajo inventado.

---

## 2 · Inventario real

| bloque | elementos | hechos distintos | naturaleza |
|---|---|---|---|
| Tablas (5 categorías) | 58 | ~35 tablas | mezcla de esquema adelantado, capacidad inactiva y legado |
| Entrypoints sin launcher | 18 | 18 scripts | casi todo herramienta manual → sospecha de modelo de deuda equivocado |
| Task types nunca ejecutados | 8 | 8 tipos | hay que demostrar la cadena productor→efecto de cada uno |
| Estados muertos/sospechosos | 7 | 7 valores | vocabulario de estados a consolidar |
| Módulos sin importador | 3 | 3 módulos | al menos uno es duplicación probada |
| Servicio declarado sin correr | 1 | 1 | `triade-backup.service` |
| Backup sin copia reciente | 1–2 | 1 | bloqueo de cola ya retirado; falta ver la copia nueva |
| Cadena vital | 0 | — | cerrado en `d5271b5` |

---

## 3 · Fases

Orden por **riesgo de pérdida** primero, luego por **cuánto miente el grafo**,
luego por limpieza. Cada fase termina con: tests específicos → suite aplicable →
runtime certificado → grafos regenerados → runtime reiniciado → panel releído.

### Fase 1 · Cerrar la protección de datos *(en curso)*

Lo único donde un fallo pierde información irrecuperable.

1. Confirmar que se encola y ejecuta un `encrypted_backup` y aparece el fichero
   cifrado. El bloqueo de cola se retiró en `d65d222`, **pero la copia nueva
   todavía no se ha visto**.
2. Prueba de restauración completa sobre ubicación temporal: descifrado →
   gunzip → SQLite abre → `PRAGMA integrity_check` → filas verificables.
   Nunca sobre la Bodega viva.
3. `triade-backup.service` / `.timer`: decidir la política real. En este Studio
   no hay systemd gobernando el runtime —corre bajo `scripts/triade_runtime.sh`—,
   así que o el timer se instala de verdad, o el planificador es el dueño y la
   unidad se archiva. Hoy la unidad existe y no la arranca nadie: eso es
   `declared_services_not_running`, y es cierto.

**Criterio de cierre:** copia nueva restaurada y verificada + política escrita
en un solo sitio.

### Fase 2 · Que el detector deje de contar dos veces

Antes de triar 35 tablas hay que saber cuántas hay. Es la fase con mejor
relación evidencia/esfuerzo y **no toca Tríade**.

1. Unificar `alias_debt_orphan_reader` y `tables_with_writer_and_no_rows`: una
   sola categoría o una explícitamente derivada de la otra, sin doble recuento.
2. Degradar el campo `live` a lo que es. Con `similarity < 0.6` no debe
   presentarse como «gemelo» sino como sugerencia sin confirmar, y nunca debe
   usarse para decidir una migración.
3. Rellenar `reachable_writer` con alcanzabilidad real desde los entrypoints
   —la maquinaria ya existe: `code_graph.reachable_modules`—. Distinguir
   «escritor que nadie puede alcanzar» de «escritor alcanzable cuyo evento no ha
   ocurrido» es exactamente la diferencia entre `UNREACHABLE_WRITER` y
   `NEEDS_REAL_EVENT`, y hoy el informe no la puede hacer.

**Criterio de cierre:** cada tabla aparece una vez, con veredicto de
alcanzabilidad. Cada baja del contador explicada elemento a elemento.

### Fase 3 · Corregir el modelo de deuda de los entrypoints

18 elementos, y la lista es casi toda `scripts/audit_*.py`,
`backfill_*.py`, `build_*_inbox.py`, `install_systemd_units.py`. Una
herramienta de auditoría manual **debe** tener `__main__` y **no** debe tener
launcher permanente: marcarla como deuda es pedirle al repositorio que arranque
solo lo que existe para ejecutarse a mano.

Clasificar cada script (`AUDIT_TOOL`, `MIGRATION_TOOL`, `ONE_SHOT`,
`RUNTIME_SERVICE`, …) y que el detector sólo cuente los `RUNTIME_SERVICE` y
`REAL_MISSING_LAUNCHER`. La clasificación va declarada en el repositorio, no
adivinada por nombre.

**Criterio de cierre:** el recuento sólo incluye lo que de verdad debería estar
arrancado. Cada exclusión justificada individualmente.

### Fase 4 · Módulos sin importador (3)

El bloque más pequeño y el de veredicto más claro.

- **`triade/core/plan_step.py`** — Hay **dos** clases `PlanStep`:
  `triade/core/central.py:80`, que usa todo el mundo incluido
  `GovernedPlanDispatcher`, y ésta, que **no importa nadie, ni un test**. Su
  docstring dice «reemplaza la lista de strings»: es un refactor que aterrizó
  como fichero y nunca se adoptó. Comparar ambas, y `MERGE` si aporta algo o
  `ARCHIVE` si no. No importarlo artificialmente.
- **`triade/capabilities/matrix.py`** (213 líneas) — «matriz completa de
  capacidades con grafo de dependencias y salud». Se solapa con el informe de
  deuda y con `capability_registry` (tabla vacía). Decidir si es el consumidor
  que le falta a esa tabla o si duplica lo que ya hace la observabilidad.
- **`triade/core/hierarchical_pulse.py`** (243 líneas) — «extiende
  LifePulseEngine». `LIFE_PULSE` funciona sin él. Determinar si es evolución no
  conectada o alternativa abandonada.

### Fase 5 · Task types nunca ejecutados (8)

Para cada uno, demostrar la cadena `PRODUCTOR → COLA → LEASE → HANDLER → EFECTO
→ EVIDENCIA → COMPLETION` y clasificar. Con base temporal y tests aislados,
nunca fabricando tareas en producción.

Hay ya una pista fuerte: `goal_install`, `goal_lora_train` y
`write_governed_text_artifact` cuelgan de `GoalOrchestrator`, cuyo productor
sólo dispara cuando `CapabilityResolver` resuelve esa capacidad concreta —el
mismo mecanismo bajo demanda que se documentó en `d5271b5`—. Es probable que
varios sean `NO_TRIGGER_YET` legítimo y no deuda.

### Fase 6 · Triaje de las 35 tablas

Sólo después de la Fase 2, cuando cada tabla aparezca una vez y con veredicto de
alcanzabilidad. Por tabla: quién escribe, bajo qué evento, si ese evento puede
ocurrir hoy, si hay lector, y clasificación (`EXPECTED_EMPTY`, `BROKEN_WRITER`,
`UNREACHABLE_WRITER`, `DUPLICATED`, `LEGACY`, `NEEDS_REAL_EVENT`).

Ninguna fila artificial. Ninguna tabla borrada sin revisar migraciones e
historia.

### Fase 7 · Vocabulario de estados (7)

`evaluating`, `preparing`, `replanning`, `retry_wait`, `unhealthy`,
`quizas_vivo`, `nadie_lo_escribe`.

`retry_wait` **sí** lo escribe la cola (está en `ACTIVE`, `task_status.py`): es
un estado válido y poco frecuente, no deuda — hay que comprobarlo antes de
tocarlo. `quizas_vivo` y `nadie_lo_escribe` parecen literales de prueba del
propio detector. Buscar escritores reales antes de modificar ningún lector, y
consolidar en `task_status.py`, que ya se declara fuente única.

---

## 4 · Reglas que no se rompen

- Una reparación que reduzca deuda y rompa frontend, API, conversación,
  workers, memoria, aprendizaje o runtime **se rechaza**.
- Cada baja del contador se explica elemento a elemento. «Se excluyó la
  categoría» no es explicación.
- Antes de crear módulo, tabla, worker, servicio o endpoint, demostrar que no
  existe ya el equivalente. Reparar y conectar antes que crear.
- Si el detector se equivoca, se corrige el detector. Tríade no se deforma para
  darle la razón a un grafo.

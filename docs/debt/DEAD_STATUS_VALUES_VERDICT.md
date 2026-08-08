# Los siete estados: cinco eran el detector, dos eran el código

Fecha: 2026-08-08 · bloque 4 del [plan de deuda](DEBT_TRIAGE_PLAN.md).

El informe traía siete valores de estado señalados: `evaluating`,
`nadie_lo_escribe`, `preparing`, `quizas_vivo`, `replanning`, `retry_wait` y
`unhealthy`. Investigados uno a uno, **cinco no eran deuda del sistema sino del
instrumento**.

| valor | dónde se compara | veredicto |
|---|---|---|
| `nadie_lo_escribe` | `tests/test_alias_debt.py` | **TEST_ONLY** — fixture del propio detector |
| `quizas_vivo` | `tests/test_alias_debt.py` | **TEST_ONLY** — fixture del propio detector |
| `unhealthy` | `triade/workers/worker_supervisor.py` | **DEAD_STATE en módulo muerto** — ya contado |
| `preparing` | `triade/evolution/engineering_worker.py` | **ACTIVE** — lo escribe su `INSERT` |
| `retry_wait` | `triade/runtime/task_leases.py` | **ACTIVE** — rama de un ternario |
| `replanning` | `triade/core/planning_graph.py` | **ACTIVE** — destino declarado de dos transiciones |
| `evaluating` | `triade/evolution/engineering_worker.py` | **DEAD_STATE** — reparado |

Que dos de los siete fueran las fixtures de la prueba de este mismo detector no
es una anécdota: es la señal de que el instrumento medía sin mirar dónde.

## Tres reglas generales, ninguna lista de nombres

### 1 · Sólo cuenta lo que llega a ejecutarse

Una comparación que vive en un módulo al que **no llega ningún entrypoint** no
devuelve cero: no se evalúa nunca. Contarla aparte es contar dos veces el mismo
problema —el módulo muerto ya lo cuentan `modules_without_importer` y el grafo de
workers— y añade la peor clase de ruido, la que hace que un informe deje de
leerse.

`find_dead_status_values` filtra por `reachable_modules()`, la misma medida de
alcanzabilidad que ya usan las otras categorías. Con eso caen los tres primeros:
las dos fixtures viven en `tests/`, y `worker_supervisor` está marcado
`disconnected` en el grafo de workers con `live_importers: []` —hay un test que
lo fija— y sus cinco tablas ni siquiera existen en la base viva.

**El límite está probado:** `test_lo_que_ningun_entrypoint_alcanza_no_se_cuenta`
comprueba que el mismo valor **sí** se acusa cuando el módulo es alcanzable. La
regla apaga ruido, no señal.

### 2 · Un estado se escribe de más formas de las que había modeladas

Dos formas perfectamente normales no estaban:

```sql
INSERT INTO runs(id,objective,status,budget) VALUES(?,?,'preparing',?)
```
La fila **nace** con ese estado, y es tan escritura como un `SET`. Se emparejan
columnas y valores por posición, igual que hace SQLite; si las dos listas no
cuadran no se afirma nada, porque entender mal una escritura taparía un corte
real (`test_el_insert_no_empareja_a_ciegas`).

```python
status = "dead_letter" if agotado else "retry_wait"
```
Escriben las dos ramas. La regex anterior sólo veía la primera, y por eso
`retry_wait` aparecía muerto con su propia asignación a la vista.

### 3 · El mapa de transiciones es la fuente canónica

`replanning` lo escribe `goal_orchestrator` pasándolo **como argumento** a
`graph.transition(...)`, y el SQL de abajo es `SET status = ?`. Ninguna regex de
escritura puede verlo.

Lo que sí es visible y verificable es que `GOAL_TRANSITIONS` lo declara como
**destino** de dos transiciones: dentro de la máquina, es alcanzable.

Y lo importante es el reverso: un estado que **no aparece como destino de ninguna
transición** sigue siendo un valor muerto por mucho que el módulo lo nombre
(`test_un_estado_declarado_sin_transicion_de_entrada_sigue_muerto`). Declarar un
estado no es una forma barata de sacarlo del contador.

## El que sí era real: `evaluating`

```sql
SELECT ... FROM engineering_evolution_runs WHERE status IN ('preparing','evaluating')
```

El vocabulario real de esa columna tiene siete valores —`preparing`,
`awaiting_approval`, `rejected`, `approved_commit`, `deployed_canary`,
`rolled_back`, `failed`— y **`evaluating` no es ninguno**. Ningún camino del
worker lo escribe. La mitad de esa condición no podía casar nunca.

No se restaura el escritor para conservar el vocabulario viejo: se retira del
contrato. Y se centraliza, que era lo que faltaba —los estados vivían repartidos
en literales por todo el fichero, que es de donde salió el fantasma—:

```python
EVOLUTION_STATES = frozenset({...})  # los siete reales
EVOLUTION_IN_FLIGHT = frozenset({"preparing"})  # lo que busca el watchdog
```

El cambio no altera ningún resultado: en la base viva
`engineering_evolution_runs` tiene dos filas, ambas `rolled_back`, y ninguna fila
ha tenido jamás `evaluating`.

`test_el_vocabulario_declarado_cubre_todo_lo_que_se_escribe` lee con `ast` los
estados que el módulo escribe de verdad —el `INSERT`, los `SET status='...'`, las
dos ramas del ternario y lo que se pasa a `self._status(...)`— y exige que
coincidan **exactamente** con lo declarado. Si alguien añade un estado sin
declararlo, o declara uno que ningún camino escribe, se entera ahí. Y usa el
mismo `_insert_values` del detector, para que las dos lecturas del esquema no
puedan divergir.

## Lo que queda dicho para la próxima vez

El detector ya tenía escrito, en su propia cabecera, que los falsos positivos son
lo único que puede matarlo. Tenía cinco. La lección no es «afinar la regex»: es
que **una señal que no distingue el código que corre del que no, mide otra cosa**
— y en este caso llegó a medirse a sí misma.

Resultado: `dead_status_value` y `suspected_dead_status` pasan de **7 a 0**, con
un solo cambio de código y ninguna exclusión por nombre.

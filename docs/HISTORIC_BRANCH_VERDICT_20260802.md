# Veredicto de las ramas históricas · 2026-08-02

PR #10, #17, #55 y #60 llevaban entre 263 y 699 commits de retraso respecto a
`main`. El encargo era: comparar cada rama contra `main`, identificar lo que
**siga siendo único**, extraerlo a PR nuevos y pequeños, y cerrar los antiguos.

Se comparó cada una. **Resultado: no queda nada que merezca extraerse.** No por
descarte perezoso —los cuatro casos tienen una razón distinta y comprobable— sino
porque `main` recorrió el mismo terreno por otro camino, y en tres de los cuatro
casos llegó más lejos.

Lo importante de este documento no es el cierre: es dejar por escrito **por qué**,
para que nadie vuelva a abrir estas ramas dentro de seis meses creyendo que se
perdió trabajo.

---

## PR #10 · `fix/central-user-facing-response`

*Improve Central user-facing response privacy* · 5 commits · 699 detrás.

**Ya está en `main` lo que importaba.** La parte de privacidad —no filtrar el
paquete cognitivo interno en la respuesta al usuario— se absorbió:
`INTERNAL_AUDIT_TERMS` y `_wants_internal_audit` viven hoy en
`triade/core/central.py` (líneas 315, 713, 839). El fichero se reescribió entero
por otro lado (ahora es la Neurona Central con PlanGraph), así que el diff textual
sigue apareciendo enorme aunque el comportamiento ya esté.

**Lo único que no está es lo que no debe estar.** El resto de la rama es
`_deterministic_user_response`: una tabla de respuestas enlatadas, con un chiste
escrito a mano en el código y saludos fijos por coincidencia de texto.

```python
if Central._is_joke_request(text):
    return "Claro: ¿Por qué el computador fue al médico? ..."
```

Eso es exactamente la capacidad fingida que este proyecto se prohíbe. Un sistema
que responde a «hazme reír» con una cadena literal no tiene sentido del humor:
tiene un `if`. **No se extrae. Se cierra.**

---

## PR #17 · `fix/cognitive-body-ci`

*reconstruir cognitive body con CI verificable* · 9 commits · 478 detrás.

`triade/body/cognitive_body.py` no existe en `main`, así que a primera vista
parece trabajo perdido. No lo es: `CognitiveBody.snapshot()` no calcula nada.
Llama a cuatro cosas que ya existen y las mete en un diccionario:

| Llama a | En `main` ya se expone por |
|---|---|
| `get_internal_runtime_state` | `triade/core/internal_runtime.py` |
| `build_runtime_heartbeat` | `/api/runtime/heartbeat` |
| `build_learning_journal` | `apps/routes/api.py:1473` |
| `WorkerBackgroundService().status()` | `triade/workers/background_service.py` |

Es una fachada de agregación sobre cuatro contratos ya publicados, y los llama
con adaptadores perezosos para esquivar ciclos de importación — señal de que la
capa sobraba ya entonces. Añadirla hoy iría en contra de la Prioridad 2 de este
mismo corte, que es **reducir** superficies duplicadas. **Se cierra.**

---

## PR #55 · `feat/federated-observability-export`

*observabilidad y exportación auditable federada* · 3 commits · 302 detrás.

El módulo es correcto y está bien escrito. El problema es sobre qué mira:

```
federated_nodes_v2, federated_jobs, federated_evidence_assessments,
federated_exchanges_v2, federated_node_events, federated_job_events
```

**Ninguna de esas seis tablas existe en la base de producción.** Sí hay código en
`main` que las crearía (`federation/registry.py`, `evidence_gate.py`,
`exchange.py`), pero nunca llegó a ejecutarse: la federación real usa
`federated_nodes`, `federated_exchange_log`, `federated_merge_log`.

Sería observabilidad que devuelve cero sobre un esquema que nadie puebla —
un panel que siempre marca «todo en orden» porque no está enchufado. Peor que no
tenerlo. **Se cierra.** Si algún día la federación v2 se puebla de verdad, este
módulo es un buen punto de partida, y queda en la historia de git.

---

## PR #60 · `agent/triade-os-audit`

*Integrate Tríade OS and governed autonomy* · 2 commits reales · 263 detrás.

El más engañoso: el diff dice 97 ficheros y ~3.300 líneas, pero son dos commits.

### `d0fe26f` · *recover orphaned worker locks* — **superado, y por más**

Añadía `_recover_stale_lock()`: si el PID del lock está muerto, borra el fichero.
Con el PID vivo, se rinde (`return False`).

`main` ya hace eso y resuelve además el caso difícil. `recover_interrupted_runtime`
borra el lock de un PID muerto, y `_retained_lock_still_holds_authority`
(`state_store.py:442`) ataca lo que la rama no veía: **la autoridad pertenece al
run, no al proceso**. En el runtime siempre-activo el PID del lock es el de
`uvicorn`, que vive toda la sesión, así que «PID vivo» nunca demostró nada.
Rescatar el parche de la rama sería retroceder.

### `76b2f25` · *durable learning assurance controls* — **duplicaría lo que hay**

Trae ocho módulos que no están en `main` por nombre. Pero por concepto:

| Rama (23 jul) | `main` hoy |
|---|---|
| `evaluation/external_benchmark.py` | 11 módulos en `triade/evaluation/` |
| `sandbox/code_worktree.py` | 8 módulos en `triade/sandbox/` |
| `core/principal_scope.py` | `triade/constitution/autonomy.py` |
| `learning/novelty.py` | dedup en `learning/pipeline.py` + `doctor.py` |
| `planning/goal_graph.py` | tabla `planning_graph` |

`main` no ignoró estos problemas: los resolvió con más recorrido y contra el
esquema real. Meter la versión de julio encima añadiría un segundo vocabulario
para cada uno — que es literalmente la deuda que la Prioridad 2 manda pagar.
**Se cierra.**

---

## Lo que sí sale de este ejercicio

Nada de código nuevo, y dos cosas que valen más:

1. **El P0 del lock retenido está cerrado**, y ahora consta. Se creía abierto.
2. **Un criterio para la próxima vez.** Una rama con más de ~200 commits de
   retraso no se evalúa por su diff —que sólo mide divergencia— sino
   preguntando, concepto a concepto, si `main` ya resolvió el problema y con
   cuánto más recorrido. Las cuatro fallaron esa prueba.

Cerrar estas ramas no tira trabajo: quita cuatro invitaciones a fusionar código
de julio sobre un sistema de agosto.

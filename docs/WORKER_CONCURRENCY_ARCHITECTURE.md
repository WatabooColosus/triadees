# Concurrencia gobernada en los Living Workers

> Estado: **ENCENDIDA por defecto** desde el 2026-08-01.
> Se apaga con `TRIADE_WORKER_CONCURRENCY=0` o `concurrency_enabled=False`.
>
> Estuvo apagada porque al activarla `test_worker_learning_integration` pasaba
> de verde en `main` a rojo en la rama, y el fallo no se reprodujo localmente.
> Ese diagnóstico dio su resultado, y no era el que se creía: en los seis
> trabajos concurrentes de la matriz (py3.11 ×3, py3.12 ×3) el paso de pytest
> termina **al 100 %**, ese test incluido. El rojo que se le atribuía venía de
> otro paso, con una comprobación que exigía datos reales de producción en un
> runner limpio — imposible de cumplir allí, y ya corregida.
>
> Los límites siguen siendo los conservadores: 3 tareas a la vez como mucho, y
> un solo hilo para escritura de memoria y para mutación crítica. Encenderla no
> es soltar el freno de mano.
>
> El trabajo `concurrent` de la matriz **bloquea** desde el mismo commit: es el
> modo que corre en producción. El `serial` también bloquea, porque es la vuelta
> atrás, y una vuelta atrás que no se prueba no es una vuelta atrás.

## El problema que resuelve

`drain_queue()` reclamaba una tarea, la ejecutaba entera y solo entonces
reclamaba la siguiente:

```
claim → execute → complete → claim → execute → complete → …
```

`max_tasks_per_drain` **nunca significó paralelismo**: era un presupuesto de
cuántas tareas atender en fila por ciclo. El efecto práctico es que una
investigación lenta contra Ollama bloqueaba revisiones que no escriben nada.

Ahora el drenaje despacha y sigue:

```
claim → despachar al carril → claim → despachar → recoger lo terminado → …
```

## Qué corre en paralelo y qué no

| Carril | Límite nominal | Límite inicial | Qué contiene | Por qué |
|---|---|---|---|---|
| `read_only` | 4 | 2 | `pulse_check`, `pending_learning_review`, `federation_inbox_review`, `system_debt_scan`, `bodega_global_review` | Observan y reportan. No escriben estado estable, así que solaparlas no puede corromper nada. |
| `research` | 2 | 1 | `goal_research`, `research_curriculum`, `neuron_candidate_formation` | Consultan modelos o la web. Caras y lentas; con una sola GPU L4 conviene no apilarlas. |
| `evaluation` | 2 | 1 | `experimental_neuron_activity`, `neuron_education_cycle`, `self_improvement_evaluation`, `self_improvement_canary_observation` | Sandbox, medición y gates. Solapables **solo entre candidatas distintas**. |
| `memory_write` | 1 | 1 | `stable_consolidation_review`, `stable_consolidation_review`, `semantic_memory_governance`, `encrypted_backup`, `write_governed_text_artifact` | Escriben memoria gobernada. Dos escrituras simultáneas producirían una memoria que nadie puede auditar. |
| `critical_mutation` | 1 | 1 | `neuron_autopromotion`, `goal_lora_train`, `goal_install`, `goal_safe_command` | Cambian lo estable. Serial global, siempre. |

`identity_core` sigue prohibido para cualquier tarea, en cualquier carril.

### Tareas desconocidas

Un tipo sin política declarada cae al carril `critical_mutation` (serial) y emite
un `warning`. Podría escribir cualquier cosa, así que se frena de más. Un test
(`test_every_known_task_type_has_an_explicit_policy`) falla si alguien añade un
tipo y olvida clasificarlo.

## Exclusiones: lo que impide que dos tareas se pisen

El límite por carril no basta. Dos evaluaciones pueden solaparse, pero **no si
son de la misma candidata**: serían dos sandboxes escribiendo sobre el mismo
sujeto.

Cada tipo declara qué claves toma en exclusiva mientras corre. Se resuelven
contra el payload:

| Tipo | Claves |
|---|---|
| `self_improvement_evaluation` | `candidate_id`, `neuron_id`, `proposal_id` |
| `self_improvement_canary_observation` | `candidate_id`, `canary_id` |
| `experimental_neuron_activity`, `neuron_education_cycle` | `neuron_id` |
| `write_governed_text_artifact` | `target` (el fichero de destino) |
| `neuron_autopromotion` | `neuron_id` + `global_promotion` |

`global_promotion` no se lee del payload: la toma toda promoción, de modo que
**dos promociones no coexisten aunque sean de neuronas distintas**.

Si el payload no trae el valor, la clave no se toma. Eso es correcto: sin
`candidate_id` la tarea no está mutando ninguna candidata concreta.

### Por qué no hay carrera

`RunningTaskRegistry` comprueba los tres límites (global, carril, exclusiones) y
toma las claves **bajo el mismo lock**. No existe ventana entre "compruebo que
está libre" y "la tomo". Verificado con 16 hilos peleando por la misma candidata:
exactamente un ganador.

## El lease sigue siendo la autoridad

El pool **no reclama ni cierra tareas**. Solo decide si una tarea *ya arrendada*
puede arrancar ahora.

- La propiedad es del lease v2 (`AutonomousTaskStore`) con `lease_generation`.
- El heartbeat (`LeaseHeartbeat`) renueva durante toda la ejecución, también en
  las tareas largas del pool.
- El cierre atómico sigue en `_execute_autonomous_task`, que es la **única**
  función que ejecuta y cierra. `_dispatch_autonomous_task` solo decide *dónde*
  corre. No hay dos sitios capaces de cerrar una tarea.
- Si el lease se pierde, el cierre se rechaza y el resultado es `lease_lost`.

### Devolver una tarea sin castigarla

`claim()` incrementa `attempt` y exige `attempt < max_attempts`. Si un rechazo
por concurrencia consumiera el intento, **tres esperas matarían una tarea que no
llegó a ejecutarse ni una vez**.

Por eso existe `defer_unstarted()`, que descuenta el intento al devolver la
tarea. Solo acepta tareas en estado `leased`: si alguien ya la arrancó,
devolverla sería ejecutarla dos veces.

`defer()` sigue existiendo sin cambios para tareas que sí corrieron.

## Los dos rechazos posibles no son el mismo problema

- **Falta de sitio** (`global_limit`, `lane_limit`) es transitorio: se espera un
  hueco, recogiendo mientras lo que termine. Diferir aquí rompería el modo
  `once`, donde no hay ciclo siguiente que recoja lo diferido.
- **Clave de exclusión tomada** es semántico: otra tarea muta esa candidata.
  Esperar no ayuda dentro del drenaje, así que vuelve a la cola de inmediato.

## SQLite

- Cada store abre su conexión **dentro del hilo (o proceso) que la usa**. No se
  hereda ninguna del hilo principal.
- `AutonomousTaskStore` ya lo hacía, con `busy_timeout=5000`.
- `WorkerStateStore` abría **sin** `busy_timeout`: la segunda escritura
  concurrente fallaba al instante con `database is locked` en vez de esperar su
  turno. Corregido.
- La base sigue en WAL.
- Las escrituras críticas siguen serializadas por el carril `critical_mutation`.
- Verificado: 72 escrituras desde 6 hilos, sin `database is locked`.

### Un detalle que condiciona todo

`GovernedTaskExecutor` ejecuta cada handler en un proceso **`spawn`** aparte para
poder imponer el timeout. Eso obliga a picklear el método enlazado y con él la
instancia de `WorkerLoop`. Un `threading.Lock` como atributo la hace impicklable
y **tumba todas las tareas** con `cannot pickle '_thread.lock'`. Por eso el lock
del `summary` vive a nivel de módulo.

Consecuencia útil: la concurrencia real es de procesos por tarea, coordinados por
hilos en el padre. Cada tarea tiene su propio espacio de memoria y sus propias
conexiones.

## Parada

1. Se deja de aceptar tareas nuevas (`stop_accepting`).
2. Se espera un período acotado (`concurrency_shutdown_seconds`, 30 s).
3. Si algo sigue vivo, se **espera de verdad** una segunda vez (hasta
   `max(60 s, task_timeout × 2)`). Reportarlo no bastaba: mientras una tarea
   corre, este run sigue siendo el dueño de su lease.
4. Si aun así quedan tareas vivas, el run termina como
   **`completed_with_active_tasks`** (ni completado ni fallido) y **conserva el
   lock**. Soltarlo dejaría entrar a otro worker sobre la misma base — la doble
   ejecución exacta que este runtime existe para impedir. No queda huérfano:
   `recover_interrupted_runtime` detecta el lock caduco por PID muerto.

Se conservan: modo `once`, modo daemon, `max_iterations`, stop file, process
lock, wake bus, reconciliación de la cola legacy, idempotency keys, artefactos
canónicos, espejo de estado terminal, leases v2, cierre atómico y las métricas
previas.

## Configuración

```python
concurrency_enabled: bool = False  # TRIADE_WORKER_CONCURRENCY=1 para activar
max_concurrent_tasks: int = 3  # nominal: 4
read_only_workers: int = 2  # nominal: 4
research_workers: int = 1  # nominal: 2
evaluation_workers: int = 1  # nominal: 2
memory_write_workers: int = 1
critical_mutation_workers: int = 1
concurrency_shutdown_seconds: float = 30.0
```

Cuando se active, se hace con los valores conservadores, no con los nominales.
Subir a los nominales solo tras medir estabilidad real — y antes de eso hay que
entender el fallo de CI descrito arriba.

### Hardware limitado

Para esta máquina (NVIDIA L4 24 GB, 8 CPU, 31 GB RAM) los valores conservadores
son los adecuados: cada tarea es un proceso `spawn` que reimporta el paquete
completo, así que el coste por tarea no es despreciable.

Con menos de 4 CPU o sin GPU dedicada, usar `ConcurrencySettings.serial()`.

`RunningTaskRegistry.set_pressure_scale()` permite estrechar los carriles bajo
presión sin reconfigurar nada, y nunca por debajo de 1: reducir por presión no
puede congelar el runtime.

## Observabilidad

El snapshot del run incluye, refrescado en cada ciclo (no solo al cerrar, o el
observador siempre vería `running: 0`):

```json
{
  "concurrency": {
    "enabled": true,
    "global_limit": 3,
    "running": 2,
    "queued": 6,
    "pressure_scale": 1.0,
    "lanes": {
      "read_only": {"limit": 2, "running": 1},
      "research": {"limit": 1, "running": 1},
      "evaluation": {"limit": 1, "running": 0},
      "memory_write": {"limit": 1, "running": 0},
      "critical_mutation": {"limit": 1, "running": 0}
    },
    "running_tasks": [
      {
        "task_id": "task-…", "task_type": "goal_research",
        "lane": "research", "resource_class": "model",
        "thread": "triade-worker_1", "lease_generation": 3,
        "started_at": 1785519000.0, "running_seconds": 12.4,
        "exclusive_keys": ["neuron_id=n-7"]
      }
    ]
  }
}
```

No se expone razonamiento interno ni prompts.

## Validación

```bash
python scripts/run_concurrency_and_lease_validation.py
```

Trabaja sobre una **copia** de `triade/memory/triade.db` (con `backup()`, no
`cp`, para que sea consistente con WAL abierto). Producción no se toca.

## Lo que no se hizo

- No se añadió Redis, Celery ni ningún broker.
- No se creó otra cola, otro scheduler ni otro sistema de leases.
- No se convirtió el worker a `asyncio`.
- No se usó multiprocessing como mecanismo de reparto (ya lo usa el ejecutor
  para timeouts, que es otra cosa).

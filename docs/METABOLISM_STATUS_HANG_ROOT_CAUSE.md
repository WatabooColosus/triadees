# El cuelgue de `test_concurrent_status_calls` · causa raíz y evidencia

> Estado: **cerrado con causa determinada.** El test vuelve a la suite y entra
> en la matriz de concurrencia. La concurrencia gobernada de los *workers*
> sigue apagada por defecto — es otro asunto, y sigue abierto.

## Qué pasaba

`tests/test_metabolism.py::TestLifecycle::test_concurrent_status_calls` colgaba
la suite completa, siempre alrededor del 36–41 %. El test lanza diez hilos que
llaman `status()` cincuenta veces cada uno y hace `join()` **sin timeout**, así
que un bloqueo no se manifiesta como fallo: se manifiesta como una suite que no
termina nunca. Para avanzar había que pasar `--deselect`, lo que dejaba el
defecto vivo y sin mirar.

Aislado, `tests/test_metabolism.py` pasaba entero. Sólo colgaba dentro de la
suite. Esa asimetría es la pista, y resultó ser literal.

## La evidencia que lo abrió

Volcado de `faulthandler` a los 90 s, con la suite parada
(`runs/concurrency-p0/evidence/suite_with_test.log`):

| hilos | dónde |
|---|---|
| 9 | `coordinator.py:213` — esperando `with self._lock:` en `status()` |
| 1 | `coordinator.py:224` → `receipts.py:98` — **con el lock tomado**, dentro de un `SELECT` |
| 1 | `coordinator.py:665` — el hilo `metabolic-coordinator`, esperando el mismo lock |

Un hilo reteniendo el lock mientras hace E/S, y todos los demás detrás. Eso
explica la forma del cuelgue, pero no por qué el `SELECT` no terminaba: abre con
`timeout=2`, así que un `database is locked` debería levantar excepción a los dos
segundos, no colgarse.

La respuesta estaba en el lock de proceso, tres capas más abajo.

## Causa raíz: un descriptor cerrado antes de guardarlo

`_acquire_process_lock` hacía esto:

```python
lock_fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
os.write(lock_fd, str(os.getpid()).encode())
os.close(lock_fd)          # ← cerrado aquí
self._lock_fd = lock_fd    # ← y guardado después, ya muerto
```

`self._lock_fd` guardaba un número de descriptor **ya cerrado**. En Linux
`open()` devuelve siempre el descriptor libre más bajo, así que ese número se lo
llevaba el siguiente fichero que abriera el proceso. Y `_release_process_lock`
lo cerraba:

```python
os.close(self._lock_fd)   # cierra el fichero de otro
```

Medido, no supuesto:

```
acquire            -> self._lock_fd = 3
fstat(3)           -> [Errno 9] Bad file descriptor   (ya estaba cerrado)
open(victima)      -> fileno 3                        (mismo número)
release -> close(3)-> victima ilegible
```

Con una base SQLite de víctima:

```
transacción EXCLUSIVE abierta (bloqueo POSIX puesto)
release_process_lock -> close(4)
conexión            -> OperationalError: disk I/O error
otra conexión       -> database is locked
```

Ahí está el eslabón que faltaba. La conexión muere con el descriptor cerrado
por debajo, y **ya no puede ni confirmar ni deshacer**: su bloqueo POSIX queda
huérfano. Cualquier lector posterior espera un bloqueo que nadie va a soltar.

Y ahí está también por qué sólo pasaba en la suite completa: qué descriptor se
recicla, y a quién le toca, depende de cuántos ficheros llevara abiertos el
proceso. Aislado, el número 3 no era de nadie. Tras mil pruebas, sí.

`triade/workers/worker_loop.py` ya lo hacía bien —abre, escribe, cierra y no
guarda el descriptor—. El defecto era sólo del metabolismo.

## Dos defectos más del mismo lock

**El lock identificaba un nombre, no una base.** Se derivaba de
`/tmp/.triade_metabolism_{db_path.name}.lock`. Dos bases en directorios
distintos, ambas llamadas `test.db` —el caso normal en pruebas—, se bloqueaban
entre sí sin compartir un solo byte de estado. Ahora la ruta lleva el sha256
corto de la ruta absoluta.

**El release borraba locks ajenos.** `unlink` incondicional: un coordinador que
nunca llegó a adquirirlo podía dejar sin protección al que sí. Ahora hay
compare-and-delete contra el PID escrito en el fichero, y sólo si de verdad lo
adquirimos.

## `status()` no era una lectura

Aparte del cuelgue, el camino de lectura hacía dos cosas que no le tocan, las
dos **dentro del lock**:

- `self.load_config()`, que relee el YAML de disco y **reconstruye
  `self.scheduler`** cuando el hilo no está vivo;
- la consulta SQLite.

Lo primero tiene una consecuencia que no es de rendimiento sino de datos:

```
cycle_count real = 7   ->   status() devolvía 0   y dejaba 0
```

Preguntar cuántos ciclos llevaba el metabolismo **lo ponía a cero**. Y
`GET /api/runtime/metabolism/status` no pide clave.

Medido en el mismo banco, antes y después:

| | antes | después |
|---|---|---|
| `cycle_count` real 7, reportado | 0 | 7 |
| reemplaza el objeto `scheduler` | sí | no |
| 200 `status()`, llamadas al sistema | 1202 | 802 |
| latencia media | 0,265 ms | 0,135 ms |

Recargar configuración es trabajo de `load_config()` y `start()`, que se llaman
a propósito. La E/S de la base se hace ahora fuera del lock; el lock sólo cubre
copiar el diccionario.

## Cómo quedó verificado

- Suite completa **con** el test y **sin** `--deselect`: 1749 pruebas, 1749
  puntos, 0 fallos, 0 errores, 100 %, sin `Timeout` de `faulthandler`. Antes se
  paraba en el 36–41 %.
- 100 repeticiones seguidas del nodo que colgaba.
- `mypy triade`: limpio, 350 ficheros.
- `ruff check` y `ruff format --check` sobre lo tocado: limpios.
- Cada defecto tiene prueba que falla antes y pasa después
  (`TestStatusIsARead`, `TestProcessLock`).

## Lo que esto NO cierra

`test_worker_learning_integration` sigue rojo en el trabajo concurrente de la
matriz, y sigue sin causa determinada. Por eso el trabajo `concurrent` conserva
`continue-on-error: true` y la concurrencia de los *workers* sigue apagada por
defecto. Cerrar un cuelgue no da por buena una capacidad entera.

Queda además abierto, y es un P0 distinto (ver `TECHNICAL_DEBT.md`): un run que
cierra con tareas vivas conserva el lock de los *workers*
(`_retain_lock_for_active_tasks`), y `recover_interrupted_runtime` sólo lo
recupera si el PID murió. En el runtime siempre-activo el PID es el de
`uvicorn`, que vive toda la sesión: el lock retenido no se recupera nunca. Es
literalmente "una tarea puede detener todo el sistema", y necesita un contrato
de autoridad con lease y generación, no un parche.

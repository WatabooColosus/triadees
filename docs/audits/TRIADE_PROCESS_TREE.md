# TRIADE_PROCESS_TREE.md — Árbol real padre→hijo

**SHA auditado:** `e3cba75be71561bc2fac006ddab76059884bcb5a`
**Fecha:** 2026-07-31
**Método:** lectura de código + inspección de `/proc/<pid>/task` del sistema en vivo.
**Alcance:** Fase 1 (inventario) y Fase 2 (proceso padre) de la auditoría forense.

Toda afirmación marcada **[E]** = evidencia directa (código leído o comando
ejecutado). **[I]** = inferencia. **[H]** = hipótesis. **[NV]** = NO VERIFICADO.

---

## 0. Inventario estructural (Fase 1, parcial)

**[E]** Medido con `git ls-files` y `find` sobre el SHA auditado:

- 647 archivos `.py` rastreados en git.
- 95.425 líneas en `triade/` + `apps/` + `scripts/`.
- 33 paquetes bajo `triade/`.

Distribución real por paquete (archivos `.py` de primer nivel):

| Paquete | .py | Paquete | .py |
|---|---|---|---|
| `triade/core` | 107 | `triade/federation` | 12 |
| `scripts` | 55 | `triade/metabolism` | 11 |
| `triade/runtime` | 24 | `triade/learning` | 10 |
| `triade/memory` | 23 | `triade/models` | 10 |
| `triade/neuron_factory` | 17 | `triade/regression` | 10 |
| `triade/workers` | 13 | `triade/capabilities` | 8 |
| `triade/qualia` | 13 | `triade/evaluation` | 8 |
| `triade/os` | 7 | `triade/sandbox` | 8 |
| `apps` | 7 | `triade/self_improvement` | 8 |
| `triade/training` | 6 | `triade/neurons` | 5 |
| `tests` | 240 | resto | 1–4 c/u |

**Nota de alcance [NV]:** la tabla completa componente-por-componente exigida por
la Fase 1 (con columnas Padre/Hijos/Caller real/Persistencia/Estado para cada uno
de los ~647 archivos) **no está completa en este documento**. Este documento cubre
el árbol de procesos (Fase 2) con evidencia dura. El inventario exhaustivo queda
pendiente.

---

## 1. Distinción de tipos (exigida por la auditoría)

El sistema **no** es un árbol de procesos Linux independientes. Los niveles reales son:

| Tipo | Cuántos hay | Evidencia |
|---|---|---|
| Proceso del SO (systemd) | 4 activos | `systemctl show` |
| Hilo daemon de Python | 7 declarados en código, ≤11 vivos en API | `grep threading.Thread` + `/proc/<pid>/task` |
| Async task | 0 propios de Tríade | ver §5 |
| Scheduler cooperativo (NO hilo) | 1 (`EventDrivenScheduler`) | `worker_loop.py:288,401` |
| Subproceso hijo efímero | 1 mecanismo | `governed_task_executor.py:226` |
| Worker lógico (fila SQLite) | N filas | tabla `autonomous_tasks` |
| Servicio externo | 1 (Ollama) | proceso propio, HTTP :11434 |
| Storage | 1 SQLite + FS | `triade/memory/triade.db` |

---

## 2. Procesos del sistema operativo (nivel 1)

**[E]** Verificado con `systemctl show ... -p MainPID` y `ss -tlnp`:

```
systemd (PID 1)
├── triade-ollama.service    → PID 346892  `ollama serve`            LISTEN 127.0.0.1:11434
├── triade-api.service       → PID 800638  `uvicorn apps.single_port_app:app`  LISTEN 0.0.0.0:8010
├── triade-workers.service   → PID 772056  `python scripts/runtime_workers.py`  (sin puerto)
├── triade-watchdog.service  → PID 93010   `python scripts/runtime_watchdog.py` (sin puerto)
├── triade-backup.service    → oneshot, inactive (disparado por timer)
└── triade-backup.timer      → enabled
```

**[E]** Ollama es un **servicio externo real**, binario Go independiente, no un hilo
de Python. Los `llama-server` que aparecen bajo él son subprocesos suyos, no de Tríade.

---

## 3. Proceso padre real: `triade-api.service`

**[E]** El entrypoint real de producción es `apps/single_port_app.py`. El arranque
ocurre en un **lifespan handler de FastAPI**, no en el nivel de módulo:

- `apps/single_port_app.py:36-37` — `@asynccontextmanager async def lifespan(app)`
- `apps/single_port_app.py:152` — `app = FastAPI(..., lifespan=lifespan)`

### 3.1 Secuencia de arranque exacta (orden real del código)

| # | Acción | Línea | Efecto |
|---|---|---|---|
| 1 | `IdentityContinuity(...).verify()` | `:41-43` | **GATE de identidad** |
| 2 | Si `integrity != "verified"` → `yield` y **return** | `:45-54` | Aborta TODO el background |
| 3 | Si `is_test_runtime()` o `TRIADE_DISABLE_BACKGROUND=1` → return | `:56-63` | Aísla tests |
| 4 | `NODE_LIVE_REGISTRY.start()` | `:64` | hilo `triade-node-live-registry` |
| 5 | `OrchestratorCoordinator().cleanup()` | `:70-71` | limpia locks expirados |
| 6 | `ensure_foundational_neurons()` | `:91` | siembra neuronas base |
| 7 | `start_model_acquisition_background()` | `:92` | hilo `triade-model-acquisition` |
| 8 | `LIFE_PULSE.configure_continuous_runner(...)` | `:94-101` | configura autonomía |
| 9 | `LIFE_PULSE.start()` | `:102` | hilos `triade-life-pulse` + `triade-continuous-runner` |
| 10 | `start_always_on_if_enabled()` | `:108` | hilo `triade-internal-runtime` |
| 11 | `start_workers_if_configured(cfg)` | `:109` | hilo `triade-workers-always-on` |
| 12 | `get_coordinator().load_config()` + `.start()` | `:115-119` | hilo `metabolic-coordinator` |

**[E] Hallazgo — el gate de identidad es real y bloqueante:** si la verificación de
integridad de identidad falla, el proceso arranca la API pero **no inicia ningún
hilo de fondo** (`:45-54`). Esto es una protección real, no declarativa.

**[E] Hallazgo — arranque del metabolismo confirmado:** el metabolismo **sí** se
inicia automáticamente en producción desde el proceso API (`:115-119`). No depende
de un script manual. Su excepción está capturada y degradada a
`{"status": "error", "detail": ...}` (`:120-121`) — es decir, **si el metabolismo
falla, el resto del sistema arranca igual** y el fallo queda solo en el payload de
estado.

### 3.2 Hilos daemon reales del proceso API

**[E]** Los 7 creadores de hilos en código de producción (`grep threading.Thread`):

| Hilo (`name=`) | Creado en | daemon |
|---|---|---|
| `triade-life-pulse` | `triade/core/life_pulse.py:152` y `:233` | sí |
| `triade-continuous-runner` | `triade/core/life_pulse.py:163` y `:217` | sí |
| `triade-internal-runtime` | `triade/core/internal_runtime.py:83-91` | sí |
| `metabolic-coordinator` | `triade/metabolism/coordinator.py:170-171` | sí |
| `triade-workers-always-on` | `triade/core/worker_autostart.py:159-160` | sí |
| `triade-model-acquisition` | `triade/core/model_acquisition.py:216-217` | sí |
| `triade-node-live-registry` | `triade/federation/node_live_registry.py:56-57` | sí |

**[E]** Conteo real en vivo: `/proc/800638/task` → **12 hilos** (1 main + iou-sqp
del kernel + ~10 de Python). Consistente con 7 hilos de Tríade + hilos internos de
uvicorn/anyio. **[NV]** No se pudo mapear tid→nombre-de-hilo-Python: `py-spy` no
está instalado en el entorno y no se quiso instrumentar el proceso de producción.

**[E] Todos son `daemon=True`.** Implicación **[I]**: al terminar el proceso
principal, mueren sin ejecutar limpieza propia.

### 3.3 Apagado (shutdown) — hallazgo

**[E]** `apps/single_port_app.py:147-149`, el bloque `finally` del lifespan solo
detiene **dos** de los siete hilos:

```python
finally:
    NODE_LIVE_REGISTRY.stop()
    LIFE_PULSE.stop()
```

**[E] No se llama** a `stop_internal_runtime_background()`, ni a
`stop_workers_always_on()`, ni a `coordinator.stop()`, ni al de model_acquisition.
**[I]** Al ser `daemon=True` el proceso igualmente termina, pero estos hilos no
ejecutan su ruta de apagado ordenado (liberar lock, marcar estado, cerrar ciclo).
**[H]** Esto podría explicar locks o ciclos que quedan marcados como abiertos tras
un `systemctl restart` — no confirmado en esta fase.

---

## 4. Proceso `triade-workers.service` — hallazgo principal

**[E]** `scripts/runtime_workers.py` (11 líneas, leído completo) llama
`WorkerBackgroundService().start(max_iterations=1_000_000, sleep_seconds=60,
task_timeout=30)` **en el hilo principal, de forma bloqueante**.

**[E]** Verificación en vivo: `/proc/772056/task` → **1 solo hilo**. Confirma que
este proceso **no** arranca LifePulse, ni metabolismo, ni internal-runtime. Solo
corre el bucle de workers.

**[E]** El `EventDrivenScheduler` ("live_scheduler") **no es un hilo**: se crea en
`worker_loop.py:288` y se ejecuta cooperativamente dentro del bucle principal con
`live_scheduler.execute_due()` (`:401`) y `live_scheduler.wait(...)` (`:405`).
Registra 2 jobs: `heartbeat` (`:377`) y `dispatch` (`:385`).

### 4.1 DOS ejecutores de workers sobre la misma base de datos

**[E]** Existen dos rutas que ejecutan `WorkerBackgroundService.start()` con el
**mismo `db_path` y `runs_dir`**:

1. Hilo `triade-workers-always-on` dentro del proceso API
   (`worker_autostart.py:127-134` → `service.start(...)`).
2. Proceso systemd `triade-workers.service` (`scripts/runtime_workers.py:7`).

**[E] La exclusión mutua es real y correcta.** `worker_loop.py:217-229`:

```python
# Atomic lock: O_CREAT|O_EXCL evita carrera TOCTOU entre múltiples instancias.
fd = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
os.write(fd, RuntimeProcessLock.payload())
...
except FileExistsError:
    return {"status": "locked", ...}
```

Más una comprobación previa de dueño vivo en `:209-216`
(`recover_interrupted_runtime` → `status == "live_owner"` → return `locked`).

**[E] Quién tiene el lock ahora mismo** (`runs/background/.triade_workers.lock`):

```json
{"pid": 772056, "command_line": ".../python scripts/runtime_workers.py ",
 "start_time": 2035419, "expected_token": "triade", ...}
```

→ El proceso systemd es el ejecutor real. El hilo dentro del API pierde la carrera
y retorna de inmediato. **Conclusión [E]: no hay doble ejecución de tareas.**

### 4.2 Hallazgo P2 — el endpoint reporta un hilo vivo que está muerto

**[E]** Respuesta real de `GET /api/runtime/workers-always-on/status`:

```
active = True        status = running
thread_alive = False lock_file_active = True   restart_attempts = 3
```

**[E] Causa exacta** — `triade/core/worker_autostart.py:219`:

```python
raw_active = bool(thread_alive or service_status.get("running"))
```

donde `service_status["running"]` viene de `background_service.py:92`
(`payload["running"] = self._lock_owner_alive()`), que comprueba si el **dueño del
lock** está vivo — y ese dueño es **el otro proceso**, no este hilo.

**[E]** Resultado: `raw_active = False or True = True` → `active=True` →
`status="running"` (`:225-227`), pese a que el hilo de este proceso está muerto.

**Clasificación honesta: P2, no P0.** El dato "hay workers corriendo" es
verdadero; lo incorrecto es la **semántica del componente**: un endpoint llamado
`workers-always-on` (que describe el hilo embebido) informa `running` sobre un hilo
que no existe. `thread_alive` sí expone la verdad y está en la respuesta.
**[E]** `restart_attempts = 3` indica que el watchdog reintentó levantar ese hilo 3
veces; cada intento pierde la carrera del lock. **[I]** Esfuerzo desperdiciado,
sin daño a los datos.

---

## 5. Async tasks

**[E]** `grep` de `asyncio.create_task` / `ensure_future` en `triade/` y `apps/`:
**no se encontró ninguno propio de Tríade**. Todo el paralelismo de fondo usa
`threading`, no asyncio. Las únicas corrutinas son los handlers de FastAPI y el
propio `lifespan`. **[I]** Implicación: el trabajo de fondo corre en hilos sujetos
al GIL, compartiendo el proceso con el servidor HTTP.

---

## 6. Subprocesos hijo efímeros

**[E]** `triade/runtime/governed_task_executor.py:226` — `subprocess.Popen(...)`.
Es el mecanismo por el que una tarea gobernada se ejecuta **fuera del proceso
worker**, con terminación controlada (`:301`, `grace_seconds`). **[E]** Se observó
en vivo un traceback real de este mecanismo (`SpawnProcess-3` ejecutando
`_encrypted_backup`), lo que confirma que **se usa de verdad**, no es teórico.

---

## 7. Árbol consolidado

```
systemd (PID 1)
│
├── triade-ollama.service ─ PID 346892 ─ [servicio externo, binario Go]
│     └── llama-server (subprocesos de Ollama, no de Tríade)  ← HTTP 127.0.0.1:11434
│
├── triade-api.service ─ PID 800638 ─ uvicorn/single_port_app  ← HTTP 0.0.0.0:8010
│     │  (arranque: apps/single_port_app.py:36-149, lifespan)
│     │  GATE: identidad verificada (:41-54) — si falla, NADA de lo de abajo arranca
│     ├── [hilo] triade-node-live-registry   ← node_live_registry.py:56
│     ├── [hilo] triade-model-acquisition    ← model_acquisition.py:216
│     ├── [hilo] triade-life-pulse           ← life_pulse.py:152
│     ├── [hilo] triade-continuous-runner    ← life_pulse.py:163/217
│     ├── [hilo] triade-internal-runtime     ← internal_runtime.py:83
│     │       └── supervisor.run_forever() → run_once() cada interval_seconds
│     ├── [hilo] metabolic-coordinator       ← metabolism/coordinator.py:170
│     │       └── _run_loop() → tick()
│     └── [hilo] triade-workers-always-on    ← worker_autostart.py:159
│             └── PIERDE la carrera del lock O_EXCL → retorna "locked" y muere
│                 (pero el endpoint lo reporta como running — §4.2)
│
├── triade-workers.service ─ PID 772056 ─ scripts/runtime_workers.py
│     │  1 SOLO HILO (verificado en /proc)  ← DUEÑO REAL del lock de workers
│     └── WorkerLoop.run() [hilo principal, bloqueante]
│           ├── (cooperativo, NO hilo) EventDrivenScheduler
│           │     ├── job "heartbeat"  ← worker_loop.py:377
│           │     └── job "dispatch"   ← worker_loop.py:385
│           └── por tarea: subprocess.Popen ← governed_task_executor.py:226
│                 └── [proceso hijo efímero] ejecuta el handler gobernado
│
├── triade-watchdog.service ─ PID 93010 ─ scripts/runtime_watchdog.py
│     └── [NV] acción correctiva real no auditada en esta fase
│
└── triade-backup.timer → triade-backup.service (oneshot)
      └── scripts/runtime_backup.py

STORAGE compartido por TODOS los anteriores:
  └── SQLite  triade/memory/triade.db   (+ WAL)   [NV] modo de concurrencia no auditado aquí
  └── FS      runs/background/<run_ref>/...  (artifacts, receipts)
  └── FS      runs/background/.triade_workers.lock  (lock O_EXCL)
```

---

## 8. Respuestas directas de la Fase 2

| Pregunta | Respuesta | Evidencia |
|---|---|---|
| ¿Cuál es el proceso padre? | `triade-api.service` (uvicorn/single_port_app) | `deploy/systemd/triade-api.service` |
| ¿Dónde nace Tríade? | `apps/single_port_app.py:36-149` (lifespan) | [E] |
| ¿Qué la mantiene viva? | 7 hilos daemon en el API + 1 proceso workers dedicado | [E] |
| ¿Los workers son un hilo o un proceso? | **Ambos existen**; gana el proceso systemd por lock O_EXCL | [E] §4.1 |
| ¿El metabolismo arranca solo? | Sí, desde el API (`:115-119`) | [E] |
| ¿Hay async tasks? | No, ninguna propia | [E] §5 |
| ¿Hay doble ejecución de tareas? | No — lock atómico O_EXCL | [E] `worker_loop.py:217` |
| ¿El apagado es ordenado? | No — solo 2 de 7 hilos se detienen | [E] §3.3 |

---

## 9. Límites de esta fase

- **[NV]** Mapeo tid→nombre de hilo Python en vivo (falta `py-spy`).
- **[NV]** Tabla exhaustiva de inventario para los 647 archivos (Fase 1 completa).
- **[NV]** Watchdog: qué acción correctiva ejecuta realmente.
- **[NV]** Fases 3–17 (Runtime Always-On en detalle, Metabolismo, Workers,
  Runner, Contexto, Neuronas, Memoria, Modelos, LoRA, Ocultos, Matriz,
  Ejecución, Riesgos, Remediación) — **no cubiertas en este documento**.

# Living Workers — Diseño Técnico

> Tríade Ω · Workers formales controlados para ciclos de neuronas persistentes.

## Visión General

Los Living Workers ejecutan tareas de fondo de forma segura, auditble y controlada. Cada worker run es un ciclo con lock, stop file, sandbox y trazabilidad completa.

## Arquitectura

```
triade/workers/
├── contracts.py          # WorkerTask, WorkerRunConfig, task types
├── task_queue.py         # Cola persistente SQLite
├── state_store.py        # Persistencia SQLite (runs, tasks, events, state)
├── scheduler.py          # Planificador de ciclos
├── worker_loop.py        # Loop principal con sandbox y handlers
├── background_service.py # Servicio de alto nivel (once/start/stop/status)
└── __init__.py           # Exportaciones públicas
```

## Contratos

### WorkerTaskType
Tareas soportadas:
- `pulse_check` — Pulso del sistema
- `pending_learning_review` — Revisión de candidatos pendientes
- `semantic_memory_governance` — Gobernanza de memoria semántica
- `neuron_candidate_formation` — Formación de candidatos
- `experimental_neuron_activity` — Actividad de neuronas experimentales
- `neuron_autopromotion` — Auto-promoción de neuronas
- `federation_inbox_review` — Revisión de federación
- `memory_consolidation_review` — Revisión de consolidación
- `system_debt_scan` — Escaneo de deuda del sistema

### WorkerRunConfig
```python
max_iterations: int = 1
sleep_seconds: float = 5.0
task_timeout: float = 30.0
dry_run: bool = False
once: bool = True
daemon: bool = False
runs_dir: str = "runs/background"
lock_file: str = ".triade_workers.lock"
stop_file: str = ".triade_stop"
```

## Control de Ejecución

### Lock File (`.triade_workers.lock`)
- Se crea al iniciar un worker run
- Contiene el PID del proceso
- Se elimina al terminar (finally)
- Si existe, otro worker no puede arrancar

### Stop File (`.triade_stop`)
- Se crea con `request_stop()`
- El loop lo verifica en cada iteración
- Se limpia con `clear_stop()` antes de iniciar

### Modos
- `once=True` — Ejecuta una iteración y termina
- `daemon=True` — Ejecuta `max_iterations` con `sleep_seconds` entre cada una
- `dry_run=True` — Registra tareas pero no las ejecuta

## Sandbox

Cada tarea se ejecuta dentro de un `WorkerSandbox` que:
- Solo permite tareas conocidas (`ALLOWED_TASKS`)
- No tiene acceso a shell ni red
- Registra artifacts en `runs/background/YYYYMMDD-HHMMSS/task-{id}-{type}/`
- Tiene timeout por tarea

## Endpoints API

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/workers/status` | Estado del worker service |
| POST | `/workers/run-once` | Ejecutar una iteración |
| POST | `/workers/start` | Iniciar daemon |
| POST | `/workers/stop` | Solicitar stop |
| GET | `/workers/events` | Eventos recientes |
| GET | `/workers/queue` | Cola de tareas |

## CLI

```bash
# Ejecutar una vez
python triade_digimon.py workers once

# Ejecutar con dry-run
python triade_digimon.py workers once --dry-run

# Estado
python triade_digimon.py workers status

# Parar
python triade_digimon.py workers stop
```

## Integración con QualiaBus

- Workers no escriben memoria estable directamente
- Solo promueven a `experimental` (nunca a `stable`)
- Cada promoción requiere `source_ref` y verificación
- `identity_core` es intocable
- Los candidatos de aprendizaje entran como `candidate`

## Políticas de Seguridad

- **identity_core_modified**: Siempre `False`
- **stable_memory_auto_write**: Siempre `False`
- **external_network_by_default**: Siempre `False`
- **audit_artifacts**: `runs/background/YYYYMMDD-HHMMSS/`

## Persistencia

### Tablas SQLite
- `worker_runs` — Ciclos de ejecución
- `worker_tasks` — Cola de tareas
- `worker_events` — Eventos de auditoría
- `worker_state` — Estado clave-valor

### Migración
`triade/memory/migrations/003_living_workers.sql`

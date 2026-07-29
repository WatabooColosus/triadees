# Fase 02 · Retiro controlado de legacy

Fecha: 2026-07-29 UTC

Base: `92d8550c1da6c79b40a7fa1407ea232839fa0fd8`

Estado: `completed` para el cambio de autoridad; tablas conservadas

## Autoridad canónica

`WorkerTaskQueue` escribe ahora directamente en `autonomous_tasks`. El loop reclama
primero y ejecuta exclusivamente identidades v2 con lease y fencing. La segunda
pasada del loop se conserva solo para reconciliar filas históricas de
`worker_tasks`; no es productora nueva.

Productores migrados:

- scheduler de Living Workers mediante `WorkerTaskQueue` v2;
- Goal Orchestrator mediante `WorkerTaskQueue` v2;
- Event Engine mediante `WorkerTaskQueue` v2;
- Neuron Scheduler mediante `WorkerTaskQueue` v2.

Consumidores legacy restantes son read-only, métricas o reconciliación temporal:
Mission Planner consulta fallos históricos, Service Health observa backlog,
Hipotálamo observa contadores y `LegacyTaskReconciler` refleja la verdad v2.

## Migración 019

`019_legacy_retirement.sql` es aditiva e idempotente. Crea:

- `runtime_queue_compatibility`;
- `runtime_queue_compatibility_events`;
- trigger SQLite `block_new_legacy_worker_tasks`.

El trigger bloquea inserts directos incluso si un productor evita las APIs Python.
No se eliminan ni alteran destructivamente tablas o filas históricas.

Modo inicial:

```text
mode = v2_canonical
legacy_writes_enabled = 0
```

## Rollback operativo

`LegacyCompatibilityController.set_compatibility()` permite una ventana explícita,
nominal y auditada. Requiere `actor` y `reason`. Activar compatibilidad habilita
temporalmente inserts legacy; desactivarla restaura el trigger sin migración inversa.

Esto es rollback de activación, no retorno de autoridad: durante compatibilidad la
tarea aún debe reconciliarse hacia v2 antes de ejecutarse. No existe ejecución
directa desde una fila legacy.

## Métricas

`LegacyCompatibilityController.metrics()` publica:

- modo vigente;
- filas legacy totales;
- filas enlazadas a v2;
- filas pendientes de reconciliación;
- filas v2 totales;
- enlaces duplicados.

## Ventana de compatibilidad ejecutada

Comando:

```bash
python scripts/run_phase_02_legacy_retirement.py
```

El runner creó una DB SQLite temporal, habilitó una ventana acotada, escribió tres
tareas legacy, cerró writes, las enlazó a tres identidades v2, aplicó estados
terminales no exitosos, reconcilió dos veces y ejecutó un drill de rollback.

Resultado:

- duplicados: 0;
- pérdidas: 0;
- legacy enlazadas: 3/3;
- pendientes tras reconciliación: 0;
- primera reconciliación: 3 reparadas, 0 errores;
- segunda reconciliación: 0 reparadas, 0 errores;
- write legacy fuera de ventana: bloqueado por SQLite;
- rollback de compatibilidad: verificado;
- deduplicación activa v2: verificada;
- orden de prioridad: verificado.

Bundle: `artifacts/triade_verify/phase_02/legacy_retirement.json`

SHA-256:
`6bd64b95cae0f1cfc86cdf61922f41e1caef41f059bad609ce39e41d98c21afa`.

## Pruebas y gates

- Suite completa `pytest -q`: exit code 0, 100 %.
- `tests/operational_truth`: 18 aprobadas.
- Test de concurrencia: 101 tareas, 0 duplicados, 0 artefactos ausentes,
  0 tareas perdidas, integridad SQLite `ok`.
- `compileall`: aprobado.
- `ruff format --check .`: aprobado, 724 archivos.
- Pruebas focales de legacy, worker, goal, event y neuron scheduler: 50 aprobadas.
- `ruff check .`: pendiente, 813 incidencias.
- `mypy triade`: pendiente, 224 errores en 68 archivos.

Ruff/mypy no se presentan como aprobados y permanecen asignados a Fase 18.

## Límites

- `worker_tasks` no se elimina; queda disponible para lectura, auditoría y
  reconciliación histórica.
- No se ejecutó una ventana productiva de 24 horas. La ventana de esta fase prueba
  contratos e idempotencia local; la estabilidad prolongada corresponde a Fase 17.
- La compatibilidad no se activa automáticamente.

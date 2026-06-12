# Triade Living Workers

## Propósito

`triade/workers/` agrega una capa operacional continua para que Tríade ejecute ciclos seguros en segundo plano sin depender de comandos manuales por cada paso.

El worker no reemplaza al `TriadeRunner`: lo complementa. El runner sigue cerrando runs conversacionales auditables; los workers procesan tareas periódicas sobre aprendizaje, memoria, neuronas experimentales, autopromoción, federación local y deuda del sistema.

## Tareas periódicas

Cada ciclo agenda y ejecuta estas tareas:

- `pulse_check`
- `pending_learning_review`
- `semantic_memory_governance`
- `neuron_candidate_formation`
- `experimental_neuron_activity`
- `neuron_autopromotion`
- `federation_inbox_review`
- `memory_consolidation_review`
- `system_debt_scan`

## Controles

- Nada modifica `identity_core` automáticamente.
- Nada escribe memoria estable desde workers.
- La memoria revisada por workers puede llegar como `experimental`, no como `stable`.
- No hay shell arbitrario.
- No hay red externa por defecto.
- Cada tarea pasa por `Safety`.
- Cada ciclo crea artefactos en `runs/background/YYYYMMDD-HHMMSS-*`.
- El loop usa lock file `.triade_workers.lock` para evitar doble ejecución.
- Stop file `.triade_stop` permite detener antes de iniciar o entre iteraciones.
- `max_iterations`, `sleep_seconds`, `task_timeout`, `dry_run`, `once` y `daemon` acotan la ejecución.

## CLI

```bash
python triade_digimon.py workers once
python triade_digimon.py workers start --max-iterations 5 --sleep 2
python triade_digimon.py workers status
python triade_digimon.py workers stop
python triade_digimon.py workers queue
python triade_digimon.py workers events
python triade_digimon.py workers doctor
```

## API

La app single-port expone:

- `GET /workers/status`
- `POST /workers/run-once`
- `POST /workers/start`
- `POST /workers/stop`
- `GET /workers/events`
- `GET /workers/queue`
- `GET /neurons/activity`
- `GET /learning/pending`

## Persistencia

El almacenamiento vive en SQLite:

- `worker_tasks`
- `worker_runs`
- `worker_events`
- `worker_state`

La migración defensiva está en `triade/memory/migrations/003_living_workers.sql` y también queda reflejada en `schemas.sql` para DBs nuevas.

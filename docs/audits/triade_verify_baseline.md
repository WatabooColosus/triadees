# TRIADE-VERIFY-v1 · Auditoría de base

Fecha de ejecución: `2026-07-29T21:26:02Z`  
Estado: `failed`  
Alcance: Fase 0, observación y validación sin cambios de código  

## Identificación del checkout

- Repositorio: `https://github.com/WatabooColosus/triadees`
- Rama: `main`
- SHA: `24f1df9d6e9f82b90e8b5ec7b77f28a543955145`
- Commit: `fix: make concurrency validation executable`
- Estado Git inicial: limpio (`git status --short` sin salida).
- Estado Git antes de crear este informe: limpio.

## Fuentes canónicas e inspección

Se revisaron, respetando el orden de autoridad indicado:

1. `TECHNICAL_DEBT.md`
2. `docs/STATUS_CURRENT.md`
3. `README.md`
4. `docs/audits/runtime_live_truth_2026-07-29.md`
5. `docs/audits/runtime_truth_final.md`

También se inspeccionaron las migraciones runtime `009` a `018`, la estrategia de
migraciones, la suite `tests/operational_truth`, ejecutores gobernados, leases,
fencing, cierre atómico, recibos de efecto, reconciliación legacy, workers,
memoria, learning, federation, model routing, watchdog y workflows de CI.

Los dos informes de runtime se trataron como evidencia de corte, no como autoridad
cuando contradicen `TECHNICAL_DEBT.md`, `docs/STATUS_CURRENT.md` o el estado medido
en este SHA.

## Resultado de los comandos obligatorios

| Comando | Estado | Resultado observado |
|---|---|---|
| `git status --short` | `completed` | Sin salida al inicio; checkout limpio. |
| `git log --oneline -20` | `completed` | HEAD `24f1df9`; se conservaron los 20 commits para la auditoría. |
| `python -m compileall -q triade apps scripts tests` | `completed` | Exit code 0; sin errores de compilación. |
| `ruff check .` | `failed` | 844 errores: 560 `EXE002`, 256 `BLE001`, 28 `S110`. |
| `ruff format --check .` | `completed` | 718 archivos ya formateados. |
| `mypy triade` | `failed` | 215 errores en 70 archivos; 304 archivos comprobados. |
| `pytest -q` | `failed` | 6 pruebas fallidas; la suite alcanzó 100 %. |
| `pytest -q tests/operational_truth` | `completed` | 15 pruebas aprobadas. |
| `python scripts/run_runtime_concurrency_test.py` | `completed` | Exit code 0; detalle abajo. |

Entorno de herramientas: Python 3.12.11, Ruff 0.16.0, mypy 2.3.0 y pytest 9.1.1.

### Fallos de la suite completa

1. `tests/test_background_learning_without_chat.py::test_runtime_runs_without_chat_and_reports_live_thinking`: el runtime devolvió `skipped`, no `ok`.
2. `tests/test_model_cognitive_policy.py::test_learning_evaluation_requires_model_or_human_approval`: se obtuvo `evaluated`, no `requires_model`.
3. `tests/test_model_cognitive_policy.py::test_bodega_global_reports_semantic_degraded_without_ollama`: el motor semántico se declaró `available`, no `unavailable`.
4. `tests/test_ollama_blood.py::test_learning_evaluation_requires_blood_or_human_approval`: se obtuvo `evaluated`, no `requires_model`.
5. `tests/test_ollama_blood.py::test_bodega_global_reports_blood_status`: `semantic_learning_allowed` fue `True` sin Ollama Blood.
6. `tests/test_ui_react_migration.py::test_heartbeat_contains_api_server_alive`: apareció el estado no contemplado `execute_missions` en `heartbeat_truth`.

Los fallos 2–5 afectan directamente la veracidad de degradación y los gates de
aprendizaje; no son únicamente problemas cosméticos de tests.

### Concurrencia runtime

Resultado reproducible del runner solicitado:

- 101 filas de tarea y 111 llamadas de enqueue.
- 3 workers.
- 90 tareas `completed` y 11 `dead_letter`; todas contabilizadas.
- 90 efectos y 0 efectos duplicados.
- 1 lease recuperado.
- 0 artefactos ausentes.
- `db_integrity = ok`.
- Duración: 1.614407 segundos.

Este test corto demuestra sus invariantes acotadas; no sustituye una prueba de 24
o 72 horas.

## Migraciones

Existen migraciones SQL numeradas `001`–`018`. Las recientes añaden:

- `009`: tareas autónomas v2, resource ledger, health y recovery.
- `010`–`011`: educación neuronal y aplicaciones con evidencia.
- `012`: auditoría de transiciones de tareas.
- `013`: historial de heartbeat de leases y fencing generation.
- `014`: puente reversible de `worker_tasks` a `autonomous_tasks`.
- `015`: despacho de planes gobernados.
- `016`: procedencia y consumo de evidencia.
- `017`: recibos de validación de aprendizaje.
- `018`: mediciones de recursos.

Riesgos de migración observados:

- `014_legacy_v2_bridge.sql` contiene `ALTER TABLE ... ADD COLUMN` sin
  `IF NOT EXISTS`; la idempotencia depende del adaptador Python de
  `WorkerStateStore`, no del SQL ejecutado directamente.
- `triade/memory/migrations/README.md` solo enumera `001` y `002`, por lo que la
  documentación de migraciones no refleja el esquema vigente.
- No se ejecutó una migración destructiva ni se modificó la DB durante la fase 0.
- La validación completa desde una DB histórica y su restauración siguen pendientes.

## Integridad SQLite

Base inspeccionada en modo read-only: `triade/memory/triade.db`.

- Tamaño: 77,594,624 bytes.
- Tablas: 87.
- `PRAGMA quick_check`: `ok`.
- `PRAGMA integrity_check`: `ok`.
- `PRAGMA foreign_key_check`: 971 filas de violación.

Por tanto, la estructura SQLite no aparece corrupta, pero la integridad referencial
no está aprobada. No se investigaron ni repararon filas en esta fase para conservar
el baseline.

La base observada contiene 414 `autonomous_tasks`, 4,777 `worker_tasks`, 59
`autonomous_research_runs`, 76 `semantic_documents`, 15 `neurons` y 0 filas en
`learning_evidence`. Los conteos describen actividad/persistencia, no prueban
aprendizaje ni utilidad.

Se observaron 510 snapshots en `artifacts/recovery`, con 39,342,759,936 bytes
lógicos agregados. No se eliminó ninguno. La retención y la prevención de nuevas
tormentas requieren verificación operacional prolongada.

## Estado de CI

GitHub Actions para el SHA auditado no está verde:

- `Runtime Truth CI`, run `30431556061`: `failure`; `python-truth` falló,
  `frontend-truth` pasó y `required-result` falló.
- `Tríade Tests`, run `30431559078`: `failure`.
- `Measurement Core`, run `30431559149`: `success`.

Un workflow exitoso no compensa los workflows requeridos fallidos. No se afirma
branch protection verificada desde esta auditoría.

## Estado de runtime

Implementación encontrada:

- cola v2 con leases, renovación y fencing generation;
- ejecución gobernada y cierre atómico;
- artefactos y recibos de efecto/postcondición;
- reconciliación de productor legacy hacia v2;
- watchdog, recovery y heartbeat canónico;
- pipelines separados para memoria, aprendizaje, investigación, federación y
  routing de modelos.

Evidencia que sí pasa en este corte: las 15 invariantes de `operational_truth` y
el test corto de concurrencia. Evidencia que impide aprobar el runtime: suite
completa roja, gates sin Ollama que permiten evaluación/aprendizaje semántico,
971 violaciones de claves foráneas, CI rojo y ausencia de ejecución prolongada
real de 24/72 horas.

## Deuda P0/P1/P2

### P0

- Recuperación longitudinal útil de hechos, preferencias, correcciones y
  relaciones, con aislamiento autenticado por usuario.
- Restauración operativa periódica con clave y retención configuradas.
- Adaptar o bloquear de forma canónica todas las rutas legacy de ejecución.
- Corregir gates que hoy declaran evaluación y disponibilidad semántica sin el
  motor exigido por política.
- Autenticación, cuotas, aislamiento tenant y protección antiabuso para operación
  pública.
- Investigar y resolver las 971 violaciones de integridad referencial mediante
  migración/backup/restore verificables.

### P1

- Retiro controlado de la tabla/producción legacy tras una ventana real estable.
- Atribución real de recursos para workers legacy y utilidad causal.
- Estado longitudinal PV-7 por sesión sin afirmaciones emocionales subjetivas.
- Ciclo autónomo de aprendizaje completo con baseline, evaluación independiente,
  aplicación, regresión, rollback, transferencia y persistencia.
- Verificación completa de blobs/modelos e instalación con hashes obligatorios.
- Serving LoRA/PEFT canary con tráfico y aprobación nominal.
- Routing multi-modelo medido contra baseline de modelo único.
- Federación sostenida entre nodos reales con revocación y reputación.
- Chaos y operación real de 24/72 horas.

### P2

- Resolver 844 errores Ruff sin desactivar reglas.
- Resolver 215 errores mypy por fronteras.
- Actualizar la documentación de migraciones `003`–`018`.
- Continuar modularización y normalización de telemetría.
- Motor visual generativo separado, si se mantiene como objetivo.

## Riesgos

1. **Veracidad de aprendizaje:** los tests muestran que un candidato puede pasar a
   `evaluated` aun cuando la política simulada indica ausencia de Ollama Blood.
2. **Disponibilidad semántica falsa:** Bodega puede anunciar motor disponible y
   aprendizaje permitido bajo una condición de degradación inyectada.
3. **Integridad referencial:** 971 violaciones pueden producir recalls, joins,
   reconciliaciones o auditorías incompletas aunque SQLite informe `ok`.
4. **Legacy:** 4,777 filas legacy frente a 414 v2 mantienen doble autoridad y
   riesgo de divergencia hasta cerrar reconciliación/retiro.
5. **Recuperación:** 510 snapshots consumen aproximadamente 39.34 GB lógicos;
   no existe evidencia baseline de retención efectiva sobre este conjunto.
6. **Calidad/CI:** Ruff, mypy, pytest y GitHub Actions están rojos.
7. **Operación prolongada:** no hay evidencia ejecutada de 24/72 horas en este SHA.
8. **Documentación divergente:** las cifras históricas de Ruff/mypy y tablas de
   research/learning no coinciden con este corte medido.

## Bloqueos de certificación

`TRIADE-VERIFY-v1` no puede aprobarse en este baseline. Bloquean el avance de una
deuda a estado `completed`:

- suite completa: 6 fallos;
- Ruff: 844 errores;
- mypy: 215 errores;
- GitHub Actions requerido: rojo;
- integridad referencial: 971 violaciones;
- aprendizaje sin motor: gates incoherentes con la política declarada;
- long run 24/72 h: `not_executed`.

Para el long run:

- Estado: `not_executed`.
- Motivo exacto: la Fase 0 exige los comandos baseline, no una espera real de 24/72
  horas; además los gates previos están rojos.
- Comandos necesarios: `python scripts/run_24h_runtime_validation.py` y
  `python scripts/run_72h_runtime_validation.py`, una vez existan y los gates
  previos estén verdes, sin compresión temporal.

## Dictamen

La Fase 0 queda ejecutada y documentada, pero su resultado es `failed`: el repositorio
posee fundamentos reales de ejecución gobernada y pasa la suite operacional acotada,
pero el checkout actual no satisface los gates de calidad, coherencia de política,
integridad referencial, CI ni operación prolongada necesarios para
`TRIADE-VERIFY-v1`.

No se inició la Fase 1. No se hizo commit, push, merge, despliegue, migración ni
modificación de `identity_core`.

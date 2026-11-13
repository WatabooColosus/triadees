# Auditoría técnica de `aa001f3`

Base examinada: `aa001f3166d46409b904f85d5d0bfe50ad4d63c1` (`feat: governed engineering evolution runtime`). La rama de trabajo se creó directamente desde ese objeto: `agent/runtime-resilience-ledger-aa001f3`.

## Evidencia de validación base

| Comprobación | Resultado real |
|---|---|
| Checkout/base Git | Correcto; árbol limpio al comenzar |
| Instalación en venv nuevo | No ejecutable: el Studio prohíbe crear un segundo entorno y devuelve `Venv creation is not allowed` |
| Dependencias instaladas | `pip check`: correcto |
| `compileall` | Correcto |
| Suite pytest completa | Correcta, 100 %, una advertencia Starlette/httpx |
| E2E/integración existentes | Correctos |
| Ruff según CI | Fallo: 311 errores |
| mypy según CI, ejecutado sin tubería | Fallo: errores de tipos en runtime, workers, memoria, regresión y otros módulos |
| Frontend `npm ci && npm run build` | Build correcto |
| `npm audit` | Una vulnerabilidad de severidad alta |
| `pip-audit -r requirements.txt` | Sin vulnerabilidades conocidas |

El workflow base ejecuta `mypy ... 2>&1 | head -50` sin `pipefail`. Por tanto puede reportar éxito aunque mypy falle. Esto es un defecto P0 del gate, no evidencia de type safety.

## Mapa de componentes existentes

| Área | Implementación encontrada | Diagnóstico |
|---|---|---|
| Always-On | `triade/core/always_on.py`, `life_pulse.py`, `internal_runtime.py` | Arranca hilos y ciclos; no demuestra progreso por sí mismo |
| AdaptiveScheduler | `triade/workers/adaptive_scheduler.py` | Ajusta intervalos por duración/éxito; no tenía ledger diario central |
| WorkerLoop | `triade/workers/worker_loop.py` | Ejecuta handlers permitidos, safety y artefactos; usa cola legacy |
| Autostart | `triade/core/worker_autostart.py` | Reinicia hilo ausente; su watchdog era principalmente liveness |
| Heartbeat | `worker_state`, `advanced_scheduler.worker_heartbeats`, sentidos del hipotálamo | Señales fragmentadas, sin una clasificación de salud única |
| Resource Governor | `resource_governor.py`, `resource_probe.py` | Decide modo por snapshot; no contabilizaba consumo por tarea/día |
| LearningPipeline | `triade/learning/pipeline.py` | Candidatos, evidencia y gates; no constituye aprendizaje general demostrado |
| Misiones neuronales | `neuron_missions.py`, planner/executor y tablas asociadas | Existe ciclo operacional y evidencia; requiere currículo y competencia formal |
| Nutrición | `neuron_nutrition.py`, worker `research_curriculum` | Alimentación candidata; no prueba retención ni transferencia |
| Memoria semántica | `semantic_store.py`, búsqueda, gobernanza y embeddings | Persistente y gobernada parcialmente; benchmark de recuperación insuficiente |
| Investigación | `research/autonomous.py` | Registra fuentes candidatas y relevancia básica; no implementa independencia ni claims completos |
| Backup cifrado | `memory/encrypted_backup.py` | Crea/verifica y retiene; retención borra directamente y falta simulacro externo completo |
| LoRA | `training/lora_trainer.py`, `governed_lora.py` | Entrenamiento real condicionado; faltan todos los gates del flujo requerido como máquina única |
| Canary PEFT | `training/peft_canary.py` | Serving, aprobación y rollback básico; no hay limited traffic/monitoring robusto |
| Observabilidad | APIs, dashboard, worker events, métricas | Amplia pero fragmentada; no existe Cabina Viva unificada del nuevo ciclo |
| SQLite | esquema principal, migraciones 001–008 y tablas creadas desde módulos | Muchas tablas se crean ad hoc; disciplina de migración no es uniforme |
| Engineering Worker | `evolution/engineering_worker.py` | Worktree, patch, tests, revisión, aprobación y rollback; no equivale al ciclo autónomo de conocimiento pedido |

## Diferencia entre lo solicitado y lo existente

Existía actividad autónoma, persistencia y gates parciales. No existía una cadena integrada que pudiera demostrar:

1. gap real y deduplicado;
2. investigación multifuente independiente;
3. candidato con máquina de estados única;
4. educación con evaluación separada;
5. aplicación en runs;
6. mejora causal frente a baseline;
7. promoción reversible;
8. recuperación del ciclo después de reinicio.

Tampoco existían garantías suficientes de leases de tarea. `WorkerStateStore.claim_next_task()` hacía `SELECT` y después `UPDATE`; dos procesos podían observar la misma fila. El `LeaseManager` separado limpiaba y luego insertaba, pero `resource` no tenía restricción `UNIQUE`, de modo que no garantizaba exclusión por recurso.

## Riesgos P0

1. CI de mypy podía quedar falsamente verde por la tubería a `head`.
2. La cola legacy no tiene claim atómico, lease renovable ni ownership fuerte.
3. El watchdog de autostart confundía hilo/PID vivo con progreso.
4. No había contabilidad diaria central; un worker podía exceder recursos sin degradación acumulativa.
5. SQLite combina esquema central, migraciones y DDL ad hoc, elevando riesgo de deriva.
6. Ruff y mypy ya estaban rojos en el commit base.
7. Frontend conserva una dependencia con vulnerabilidad alta.
8. El backup legacy elimina archivos directamente durante retención, contrario a la nueva política de papelera reversible.

Los P0 quedaron registrados antes de iniciar cambios. La primera implementación no declara resueltos los puntos 5–8.

## Plan de ejecución por PR

1. **PR 1 — Runtime resilience:** auditoría, watchdog de progreso, recuperación controlada, cola v2 con leases e idempotencia, ResourceLedger, migración y systemd en dry-run.
2. **PR 2 — Scheduler por ritmos:** integración completa de tareas v2, ritmos, dependencias, circuit breaker persistente y observabilidad.
3. **PR 3 — Curiosidad e investigación:** gaps, deduplicación híbrida, source policy, claims e independencia.
4. **PR 4 — Conocimiento y memoria:** máquina unificada, memoria multiusuario, contradicción, olvido reversible y benchmarks.
5. **PR 5 — Educación neuronal:** competencias, currículos, separación de roles, repetición y pruebas prácticas.
6. **PR 6 — Baselines e incidentes:** LearningIncident, root cause, comparación reproducible y gates de promoción.
7. **PR 7 — Backup/LoRA/modelos:** retención reversible, simulacros, gates completos de artefactos y canary limitado.
8. **PR 8 — Cabina Viva y CI:** panel, diario, E2E de ciclo completo y cierre de lint/typing/security gates.

Cada PR debe preservar compatibilidad SQLite, incluir migración/pruebas/rollback y no promover stable automáticamente.

## Primera fase recomendada

Comenzar por PR 1. Sin exclusión atómica, señales de progreso y presupuesto acumulativo, cualquier curiosidad o educación autónoma amplifica ejecuciones duplicadas, loops y consumo no gobernado. La fase debe operar en paralelo a la cola legacy hasta demostrar recuperación y permitir una migración gradual.

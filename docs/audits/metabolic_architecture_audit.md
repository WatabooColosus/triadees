# Auditoría de Arquitectura Metabólica · Tríade Ω

**Fecha:** 2026-07-30
**SHA base:** (working tree)
**Fase:** 1/7

---

## Resumen ejecutivo

No existe un concepto explícito de "metabolismo" como sistema coordinado en el código.
Sin embargo, todas las capacidades metabólicas requeridas están distribuidas entre
`triade/runtime/`, `triade/core/`, `triade/workers/` y la configuración en
`triade.yml`. La integración actual es implícita y carece de un coordinador central,
presupuesto unificado, ciclo formalizado y receipts metabólicos.

---

## 1. Componentes reutilizables

| Componente | Archivo | Líneas | Reutilizable | Observaciones |
|---|---|---|---|---|
| `LiveHeartbeat` | `triade/runtime/live_heartbeat.py` | 89 | ✅ | Pulse/snapshot con SQLite, psutil. Sin invocación de red. |
| `ServiceHealth` | `triade/runtime/service_health.py` | 210 | ✅ | Inspecciona heartbeat, DB, disco, RAM, Ollama. |
| `RuntimeWatchdog` | `triade/runtime/watchdog.py` | 100 | ✅ | Tick con health check + recovery budget + cooldown. |
| `RuntimeRecovery` | `triade/runtime/runtime_recovery.py` | 196 | ✅ | Snapshot DB, recovery de leases, retention. |
| `EventDrivenScheduler` | `triade/runtime/event_scheduler.py` | 172 | ✅ | Scheduler monotónico sin busy loop. |
| `ResourceLedger` | `triade/runtime/resource_ledger.py` | 341 | ✅ | Budget diario + política de degradación. |
| `UtilityLedger` | `triade/runtime/utility_ledger.py` | 118 | ✅ | Receipts de utilidad separados de actividad. |
| `AutonomousTaskStore` | `triade/runtime/task_leases.py` | ~550 | ✅ | Leases atómicos, fencing, idempotencia, recovery. |
| `AtomicCompletionCoordinator` | `triade/runtime/atomic_completion.py` | - | ✅ | Completado atómico con verificación de leases. |
| `CanonicalTaskArtifacts` | `triade/runtime/task_artifacts.py` | - | ✅ | Artifacts con rollback.json. |
| `EffectReceipt` | `triade/runtime/effect_receipt.py` | - | ✅ | Receipts con postcondiciones y rollback. |
| `GovernedCapability` | `triade/runtime/governed_capability.py` | - | ✅ | Rollback verificable. |
| `WorkerScheduler` | `triade/workers/scheduler.py` | - | ✅ | Planificador con MissionPlanner + fallback. |
| `AdaptiveScheduler` | `triade/workers/adaptive_scheduler.py` | ~300 | ✅ | Intervalos adaptativos por historial. |
| `MissionPlanner` | `triade/workers/mission_planner.py` | ~500 | ✅ | Planificación inteligente basada en estado real. |
| `WorkerStateStore` | `triade/workers/state_store.py` | ~496 | ✅ | Persistencia SQLite workers. |
| `WorkerSupervisor` | `triade/workers/worker_supervisor.py` | - | ✅ | Tracking consumo, timeouts, health snapshots. |
| `LifePulseEngine` | `triade/core/life_pulse.py` | 1147 | ⚠️ | Monolito: observa, cuenta, verifica, propone candidatos. |
| `HierarchicalPulseEngine` | `triade/core/hierarchical_pulse.py` | 243 | ✅ | Pulso jerárquico con interocepción. |
| `SystemPulseBuilder` | `triade/core/system_pulse_builder.py` | 335 | ✅ | Construye dict de pulso para observabilidad. |
| `ErrorBus` | `triade/core/error_bus.py` | - | ✅ | Registro de errores internos. |
| `ObservabilityView` | `triade/core/observability_view.py` | 154 | ✅ | Vista unificada de observabilidad. |
| `ResourceGovernor` | `triade/core/resource_governor.py` | - | ✅ | Decide modo según recursos. |
| `ResourceProbe` | `triade/core/resource_probe.py` | - | ✅ | Lectura segura de hardware. |
| `RuntimeProcessLock` | `triade/runtime/process_lock.py` | - | ✅ | PID lock con verificación de identidad. |
| `ActivityBudget` | `triade.yml` (lines 74-89) | - | ✅ | Budgets por minuto/hora/día. |
| `RuntimeBudget` | `triade.yml` (lines 91-99) | - | ✅ | Budgets diarios de CPU/GPU/red/almacenamiento. |

---

## 2. Duplicaciones

| Componente A | Componente B | Riesgo |
|---|---|---|
| `LifePulseEngine._continuous_loop()` | `WorkerLoop.run()` | Ambos ejecutan ciclos periódicos; LifePulse tiene lógica de runner duplicada. |
| `LiveHeartbeat` | `LifePulseEngine.record_action()` | Heartbeat y pulse tienen tablas separadas (`live_runtime_heartbeat` vs `worker_state`). |
| `ServiceHealth._ollama_probe()` | `check_ollama_blood()` en `ollama_blood.py` | Dos caminos para probar Ollama. |
| `HierarchicalPulseEngine` | `SystemPulseBuilder` | Ambos construyen pulsos; el jerárquico usa DB, el builder usa funciones inyectadas. |
| `WorkerSupervisor` (tablas propias) | `WorkerStateStore` (tablas SQLite) | Tablas de supervisión separadas de las tablas de estado. Riesgo bajo. |
| `ResourceLedger` (tabla propia) | `ActivityBudget` en YAML | Budget en código vs budget en configuración. Budget diario se calcula en DB. |

---

## 3. Puntos de entrada

| Punto | Archivo | Método | Uso metabólico |
|---|---|---|---|
| `TriadeRunner.run()` | `triade/core/runner.py` | Ciclo cognitivo completo | Potencial punto de integración metabólica. |
| `LifePulseEngine.start()` | `triade/core/life_pulse.py` | Thread daemon | Ciclo continuo de observación. |
| `WorkerBackgroundService.start()` | `triade/workers/background_service.py` | Worker loop | Ciclo de tareas internas. |
| `RuntimeWatchdog.tick()` | `triade/runtime/watchdog.py` | Polling | Watchdog de salud con recovery. |
| `LiveHeartbeat.pulse()` | `triade/runtime/live_heartbeat.py` | Periódico | Heartbeat básico. |
| `EventDrivenScheduler.execute_due()` | `triade/runtime/event_scheduler.py` | Event-driven | Ejecución de jobs programados. |
| `AlwaysOnRuntime` | `triade/core/always_on.py` | Thread daemon | Self-tests y workers_watchdog. |
| `ServiceHealth.inspect()` | `triade/runtime/service_health.py` | Bajo demanda | Sondas de salud. |
| `InternalRuntimeSupervisor` | `triade/services/supervisor.py` | Thread daemon | Supervisor 24/7. |

---

## 4. Autoridad de estado

| Estado | Tabla/DB | Escritor | Lector |
|---|---|---|---|
| Heartbeat | `live_runtime_heartbeat` (singleton) | `LiveHeartbeat.pulse()` | `ServiceHealth.inspect()`, API |
| Tareas workers | `autonomous_tasks` | `AutonomousTaskStore` | Workers, Scheduler |
| Tareas legacy | `worker_tasks` | `WorkerStateStore` | Workers (migración a v2) |
| Health snapshots | `runtime_health_snapshots` | `RuntimeWatchdog._record()` | Observabilidad |
| Recovery events | `runtime_recovery_events` | `RuntimeRecovery.recover()` | Watchdog |
| Budget | `resource_ledger` + `resource_measurements` | `ResourceLedger.record()` | `ResourceLedger.policy()` |
| Utility | `utility_receipts` | `UtilityLedger.record()` | `UtilityLedger.summary()` |
| Pulse jerárquico | `pulse_log` | `HierarchicalPulseEngine` | Observabilidad |
| Scheduler history | `scheduler_history` + `scheduler_metrics` | `AdaptiveScheduler` | `WorkerScheduler` |
| Worker runs | `worker_runs` | `WorkerStateStore` | Workers, API |
| Worker events | `worker_events` | `WorkerLoop`, `ErrorBus` | Observabilidad |
| Worker state | `worker_state` | `WorkerStateStore` | Workers, API |
| Supervisor | `worker_consumption`, `worker_time_log`, etc. | `WorkerSupervisor` | API |
| Leases | `leases` (tabla separada) | `LeaseManager` | `LeaseManager` |
| Lease fencing | `autonomous_tasks.lease_generation` | `AutonomousTaskStore` | `AtomicCompletionCoordinator` |
| Artifacts | Filesystem + `rollback.json` | `CanonicalTaskArtifacts` | API, Recovery |

---

## 5. Tablas involucradas (79 activas)

De las ~82 tablas en la DB, las siguientes tienen relevancia metabólica directa:

| Tabla | Propósito metabólico |
|---|---|
| `live_runtime_heartbeat` | Heartbeat singleton |
| `runtime_health_snapshots` | Snapshots periódicos de salud |
| `runtime_recovery_events` | Eventos de recuperación |
| `runtime_queue_compatibility` | Compatibilidad colas legacy/v2 |
| `resource_ledger` | Contabilidad de presupuesto |
| `resource_measurements` | Mediciones detalladas de recursos |
| `worker_tasks` | Tareas legacy de workers |
| `worker_runs` | Ejecuciones de workers |
| `worker_events` | Eventos de workers |
| `worker_state` | Estado persistente de workers |
| `autonomous_tasks` | Cola autónoma v2 con leases |
| `autonomous_task_transitions` | Transiciones de estado de tareas |
| `autonomous_lease_heartbeats` | Heartbeats de lease renewal |
| `pulse_log` | Registro de pulsos jerárquicos |
| `scheduler_history` | Historial del scheduler adaptativo |
| `scheduler_metrics` | Métricas del scheduler |
| `worker_consumption` | Consumo de workers (supervisor) |
| `worker_time_log` | Logs de tiempo (supervisor) |
| `worker_ownership` | Ownership de tareas (supervisor) |
| `worker_restart_log` | Logs de restart (supervisor) |
| `worker_health_snapshots` | Health snapshots (supervisor) |
| `utility_receipts` | Receipts de utilidad |
| `leases` | Leases temporales |
| `runtime_queue_compatibility_events` | Eventos de compatibilidad |

---

## 6. Ciclos periódicos existentes

| Ciclo | Componente | Intervalo | DB | Riesgo |
|---|---|---|---|---|
| Heartbeat | `LiveHeartbeat.pulse()` | 5s (configurable) | `live_runtime_heartbeat` | Bajo |
| Life pulse tick | `LifePulseEngine._loop()` | 60s (configurable) | Múltiples tablas | Medio — monolito |
| Continuous runner | `LifePulseEngine._continuous_loop()` | 10s (configurable) | Múltiples tablas | Medio — duplica worker loop |
| Worker daemon | `WorkerLoop.run()` | 20s (configurable) | `autonomous_tasks` | Bajo |
| Scheduler adaptativo | `AdaptiveScheduler` | Por tipo de tarea | `scheduler_history` | Bajo |
| Watchdog tick | `RuntimeWatchdog.tick()` | 60s (script) | `runtime_health_snapshots` | Bajo |
| Self-test cycle | `AlwaysOnRuntime` | Cada 5 cycles | - | Bajo |
| Event scheduler | `EventDrivenScheduler` | Por vencimiento | - | Bajo |
| Internal runtime | `InternalRuntimeSupervisor` | ~20-30s | `worker_events` | Bajo |
| TriadeOS scheduler | `triadeos.scheduler.enabled` | 60s | `triadeos_event_state` | Bajo |
| Knowledge graph | `triadeos.knowledge_graph.enabled` | - | `kg_nodes`/`kg_edges` | Bajo |
| Event engine | `triadeos.event_engine.enabled` | 60s | `triadeos_event_state` | Bajo |
| Health check | `ServiceHealth.inspect()` | Bajo demanda | - | Bajo |

---

## 7. Riesgos de concurrencia

| Riesgo | Descripción | Severidad | Mitigación existente |
|---|---|---|---|
| Duplicación de worker loop | LifePulse y WorkerLoop pueden ejecutar tareas similares | Media | LifePulse usa `continuous_runner_enabled=false` por defecto |
| Heartbeat race | `LiveHeartbeat.pulse()` usa `ON CONFLICT(singleton) DO UPDATE` | Baja | Singleton con PK fija |
| Lease fencing | `AutonomousTaskStore` usa generación + lease atómico | Baja | SQLite transaccional + `lease_generation` |
| Budget race | `ResourceLedger.daily_usage()` y `record()` no son atómicos globalmente | Media | Cada registro tiene fecha; la suma es consistente al final del día |
| Worker state race | `WorkerStateStore` usa `INSERT OR REPLACE` | Baja | PK única |
| Supervisor tables | `WorkerSupervisor` crea sus propias tablas sin migraciones | Media | Tablas separadas, sin joins con tablas principales |

---

## 8. Riesgos de loops infinitos

| Componente | Riesgo | Protección |
|---|---|---|
| `LifePulseEngine._loop()` | Ciclo infinito si stop event no se señaliza | `while not self._stop.is_set()` con sleep |
| `LifePulseEngine._continuous_loop()` | Ciclo infinito si `max_cycles=0` | `max_cycles=0` = ilimitado (configurable) |
| `WorkerLoop.run()` | Daemon infinito si no hay stop | `stop_file` + `max_iterations` |
| `RuntimeWatchdog` (script) | Bucle `while True` | Solo en script independiente |
| `EventDrivenScheduler` | Re-programación infinita | `heapq` con due time, no hay loop |

**Conclusión:** Los loops tienen protecciones, pero el modo `max_cycles=0` en LifePulse es ilimitado por diseño.

---

## 9. Dependencias externas

| Dependencia | Uso metabólico | Obligatoria |
|---|---|---|
| SQLite3 | Toda persistencia | ✅ Sí |
| psutil | Heartbeat (RAM, CPU), ResourceProbe | ✅ Sí |
| Ollama (opcional) | Modelos para evaluación | ❌ No (fallback) |
| Redis (opcional) | Estado distribuido, rate limiting | ❌ No |
| cryptography | Backup cifrado | ❌ Opcional |
| PEFT/accelerate | LoRA training | ❌ Opcional |

---

## 10. Deuda técnica

| Deuda | Archivo | Impacto |
|---|---|---|
| `LifePulseEngine` monolito (1147 líneas) | `core/life_pulse.py` | Alto: mezcla observación, integridad, reflexión, promoción y auto-identidad |
| Dos tablas de heartbeat (`live_runtime_heartbeat` + `worker_state`) | runtime + workers | Bajo: convivencia legacy |
| `WorkerSupervisor` con tablas propias no migradas | `workers/worker_supervisor.py` | Bajo: tabla separada sin migración formal |
| `ResourceMeasurement.missing` para GPU/red | `runtime/resource_ledger.py` | Bajo: valores marcados como `unavailable` |
| Sin ciclo metabólico formal | Todo el código | Alto: no hay `observe→evaluate→propose→authorize→execute→verify→consolidate` |
| Sin presupuesto unificado metabólico | Config dispersa | Medio: budget en YAML, en ResourceLedger, en ActivityBudget |
| Sin receipts metabólicos | - | Alto: no hay `MetabolicReceipt` |
| LifePulse tiene `_safe_file_ops` pero no usa `GovernedCapability` | `core/life_pulse.py` | Medio: operaciones de archivo fuera del framework de rollback |

---

## 11. Pruebas existentes relevantes

| Test | Archivo | Cobertura metabólica |
|---|---|---|
| `test_life_pulse.py` | `tests/test_life_pulse.py` | ✅ LifePulseEngine: tick, snapshot, acciones |
| `test_runtime_watchdog.py` | `tests/test_runtime_watchdog.py` | ✅ Watchdog, recovery budget, cooldown |
| `test_runtime_task_leases.py` | `tests/test_runtime_task_leases.py` | ✅ Idempotencia, leases, fencing |
| `test_operational_truth/test_invariants.py` | `tests/operational_truth/` | ✅ Invariantes: leases, artifacts, rollback |
| `test_utility_ledger.py` | `tests/test_utility_ledger.py` | ✅ Utility receipts |
| `test_resource_ledger_runtime.py` | `tests/test_resource_ledger_runtime.py` | ✅ Budget ledger |
| `test_semantic_governance.py` | `tests/test_semantic_governance.py` | ✅ Gobierno de memoria semántica |
| `test_learning_pipeline.py` | `tests/test_learning_pipeline.py` | ✅ Pipeline de aprendizaje |
| `test_worker_loop.py` | `tests/test_worker_loop.py` | ✅ Worker loop |
| `test_worker_runtime_recovery.py` | `tests/test_worker_runtime_recovery.py` | ✅ Worker recovery |
| `test_background_service_once.py` | `tests/test_background_service_once.py` | ✅ Workers one-shot |
| `test_continuous_runner_24_7.py` | `tests/test_continuous_runner_24_7.py` | ✅ Runner continuo |
| `test_hierarchical_pulse.py` | (no existe) | ❌ Sin test para pulso jerárquico |
| `test_adaptive_scheduler.py` | (no existe) | ❌ Sin test específico |
| `test_process_lock.py` | (no existe) | ❌ Sin test para process lock |

---

## 12. Mapa de autoridad actual

```
                    ┌─────────────────────────────────────┐
                    │         T R Í A D E   Ω              │
                    │                                     │
  ┌─────────────────▼─────────────────────────────────────▼──────────────┐
  │                      RUNTIME V2 (autoridad canónica)                  │
  │  LiveHeartbeat · ServiceHealth · RuntimeWatchdog · RuntimeRecovery   │
  │  EventDrivenScheduler · ResourceLedger · AutonomousTaskStore         │
  │  ExecutionResult · EffectReceipt · GovernedCapability · TaskArtifacts │
  └──────────────────────┬──────────────────────────────────┬───────────┘
                         │                                  │
  ┌──────────────────────▼──────────────┐  ┌───────────────▼───────────┐
  │      CORE (LifePulseEngine)         │  │    WORKERS (WorkerLoop)   │
  │  Ciclo continuo (thread daemon)     │  │  Scheduler + MissionPlanner│
  │  Observación + integridad +         │  │  TaskQueue + StateStore   │
  │  reflexión + propuesta + auto-ID    │  │  Supervisor + Leases       │
  └─────────────────────────────────────┘  └───────────────────────────┘
```

---

## Conclusión de la auditoría

**No existe un Núcleo Metabólico formal.** Las capacidades están distribuidas,
parcialmente duplicadas y sin coordinación central. `RuntimeV2` es la autoridad
canónica de ejecución y debe seguir siéndolo. `LifePulseEngine` es el componente
más cercano a un metabolismo pero es un monolito que necesita descomposición.

El diseño debe:
1. Crear un `MetabolicCoordinator` que *use* runtime v2 (no lo reemplace)
2. Formalizar el ciclo `observe→evaluate→propose→authorize→execute→verify→consolidate`
3. Unificar presupuesto metabólico
4. Generar receipts metabólicos
5. Integrarse con workers existentes sin duplicar
6. Ser desactivado por defecto

Archivos que se crearán:
- `triade/metabolism/__init__.py`
- `triade/metabolism/coordinator.py`
- `triade/metabolism/contracts.py`
- `triade/metabolism/scheduler.py`
- `triade/metabolism/health.py`
- `triade/metabolism/receipts.py`
- `triade/metabolism/needs.py`
- `triade/metabolism/policy.py`
- `triade/metabolism/budget.py`
- `triade/metabolism/recovery.py`
- Migración SQL `memory/migrations/032_metabolic_core.sql`
- `tests/test_metabolic_core.py`
- `docs/architecture/metabolic_core.md`
- `docs/audits/metabolic_core_implementation_report.md`

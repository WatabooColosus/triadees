# TRIADE · Mapa del sistema real

Auditoría 2026-08-02 · base `75e71e7`. Este mapa describe lo que **está
cableado**, no lo que la documentación promete. Cada arista se verificó por AST
o por evidencia en la base.

---

## 1 · El circuito always-on, de verdad

```
uvicorn apps.single_port_app:app  (:8010)
  │
  ├─ MetabolicCoordinator ── tick() cada ~15 s ──────────────────────────┐
  │    │                                                                │
  │    ├─ HealthSensors.inspect()   db · disk · memory · heartbeat ·     │
  │    │                            leases · queue                      │
  │    │        ▲                                                       │
  │    │        └── P0-01: `leases` miraba `worker_tasks` (retirada)     │
  │    │                                                                │
  │    ├─ NeedsQueue.detect(sensors) ── emite necesidades CONDICIONALES  │
  │    │        health_check (siempre) · heartbeat (siempre) ·           │
  │    │        budget_check (siempre) · lease_supervision (SOLO si      │
  │    │        sensors["leases"]["ok"] es falso)                        │
  │    │                                                                │
  │    └─ _action_lease_supervision() → AutonomousTaskStore              │
  │                                       .recover_expired()            │
  │                                     status IN ('leased','running')  │
  │                                     AND lease_expires_at <= now     │
  │                                                                     │
  └─ WorkerLoop  ←── MissionPlanner.plan_cycle() ── Scheduler ──────────┘
       │                  (11 planificadores por consulta SQL)
       │
       ├─ AutonomousTaskStore.claim()   lease + lease_generation (fencing)
       ├─ ConcurrencyPool.submit()      carril + claves de exclusión
       ├─ LeaseHeartbeat.renew()        cada min(lease/3, 15 s)
       └─ handlers[task.task_type]      24 tipos
```

**Autoridad de propiedad**: solo el lease v2 (`autonomous_tasks` +
`lease_generation`). El pool de concurrencia decide si una tarea *ya arrendada*
puede arrancar; no reclama ni cierra.

---

## 2 · Los 24 tipos de tarea: productor → store → consumidor

| task_type | Productor real | Carril | Claves exclusión | Ejec. |
|---|---|---|---|---|
| `pulse_check` | `mission_planner:222` | read_only ×4 | — | 1.763 |
| `neuron_candidate_formation` | `mission_planner:614` | research ×2 | `neuron_id` | 385 |
| `learning_evidence_generation` | `mission_planner:289` | evaluation ×1 | `candidate_id` | 358 |
| `learning_candidate_deduplication` | `mission_planner:267` | memory_write ×1 | — | 334 |
| `neuron_autopromotion` | `mission_planner:331` | critical ×1 | `neuron_id`, global | 324 |
| `system_debt_scan` | `mission_planner:580` | read_only ×4 | — | 274 |
| `pending_learning_review` | `mission_planner:241,370` | memory_write ×1 | — | 205 |
| `research_curriculum` | `mission_planner:123` | research ×2 | — | 70 |
| `neuron_education_cycle` | `mission_planner:196` | evaluation ×2 | `neuron_id` | 15 |
| `encrypted_backup` | `mission_planner:84` | memory_write ×1 | — | 13 |
| `goal_safe_command` | `capability_resolver` → `goal_orchestrator:139` | critical ×1 | — | 5 |
| `goal_research` | ídem + `worker_loop:1492` (delegada) | research ×2 | — | 3 |
| `learning_candidate_generation` | **`learning/post_run.py:99`** ← ruta gobernada | memory_write ×1 | `source_run_id` | **0** |
| `self_improvement_evaluation` | `mission_planner:159` | evaluation ×2 | `candidate_id`,`neuron_id`,`proposal_id` | 0 |
| `stable_consolidation_review` | `mission_planner:451` | memory_write ×1 | — | 0 |
| `semantic_memory_governance` | `mission_planner:308` | memory_write ×1 | — | 0 |
| `federation_inbox_review` | `mission_planner:538` | read_only ×4 | — | 0 |
| `experimental_neuron_activity` | `os/neuron_scheduler:247` | evaluation ×2 | `neuron_id` | 0 |
| `bodega_global_review` | `os/event_engine` (regla `pulse_check_completed`) | read_only ×4 | — | 0 |
| `goal_install` | `goal_orchestrator:159` (requiere aprobación humana) | critical ×1 | — | 0 |
| `goal_lora_train` | `goal_orchestrator:197` (requiere aprobación) | critical ×1 | `neuron_id` | 0 |
| `write_governed_text_artifact` | `capability_resolver:41` | memory_write ×1 | `target` | 0 |
| `memory_consolidation_review` | **NINGUNO** | memory_write ×1 | — | **0** |
| `self_improvement_canary_observation` | **NINGUNO** | evaluation ×2 | `candidate_id`,`canary_id` | **0** |

Estados posibles observados: `pending`, `queued`, `leased`, `running`,
`retry_wait`, `recovered`, `deferred`, `completion_uncertain` →
`completed` / `observed` / `skipped` / `blocked` / `dead_letter`.

---

## 3 · Aprendizaje desde conversaciones — dos rutas conviviendo

```
Runner.run()  ── responde al usuario ──┐
                                       │
   ┌───────────────────────────────────┴────────────────────────────┐
   │                                                                │
RUTA ANTIGUA (activa hoy)                RUTA GOBERNADA (apagada)
runner.py:1082                           runner.py:~994
RunLearningService                       schedule_learning_from_run()
  .post_run_learning_candidate()           │ requiere TRIADE_POST_RUN_LEARNING
   │ EN LÍNEA, dentro de la respuesta      │ NO está en .env → apagada
   │ vuelca la transcripción entera        │
   ▼                                       ▼
learning_queue                           autonomous_tasks
  180 filas «run_id:… input:… response:»   task_type=learning_candidate_generation
  655 de 656 en `internally_checked`       idempotency_key=post-run-learning:{run_id}
                                           │  0 ejecuciones históricas
                                           ▼
                                        _learning_candidate_generation
                                           │
                                        ExperienceLearningCandidateProducer
                                          rechaza: rol no confiable, corto/largo,
                                          autorreferencial, especulativo
                                          NO filtra ataques a identidad ← P2-02
                                           ▼
                                        learning_queue (≤1 candidato por mensaje)
```

Aguas abajo, **común a ambas**:

```
learning_candidate_deduplication → learning_candidate_groups   (334 ejec.)
learning_evidence_generation     → learning_evidence           (358 ejec.)
        │ evidence_bridge.require_improvement()  ← gate estricto
        ▼
   evidence_verified (1, desde 2026-08-01) → stable (0)
        │
        ▼
production_injection.py  ── solo `evidence_verified` y `stable`, máx. 3/run
        │ delega en retrieval.py:216 → RetrievalSafetyPolicy.classify()
        ▼
   bloque <triade_verified_knowledge> en el contexto del run
```

---

## 4 · Educación neuronal — dónde se corta

```
laguna → neuron_curricula (8) → research_curriculum (70 ejec.)
   → neuron_education_cycle (15 ejec.)
      → neuron_education_sessions (21)
           14 → insufficient_material
            7 → lesson_prepared   ← EL CIRCUITO TERMINA AQUÍ
                baseline_score NULL · post_score NULL
                applied_run_count 0 · result 'uncertain'

   ╳ neuron_education_applications  (0 filas)   ── no existe el productor
   ╳ medición antes/después                     ── no existe
   ╳ decisión improved/neutral/degraded         ── no existe
   ╳ rollback de lección degradante             ── no existe
   ╳ neuron_certifications          (0 filas)
```

---

## 5 · Observabilidad — origen de cada dato

| Endpoint | Tabla origen | Ventana | Estado |
|---|---|---|---|
| `/api/runtime/heartbeat` | `live_runtime_heartbeat`, `metabolic_cycle` | actual | fiable |
| `/api/knowledge/summary` | `learning_queue` + `learning_candidate_groups` | de por vida | fiable, cuadra con SQL |
| `/api/learning/tasks` | `autonomous_tasks` + `learning_queue` | **24 h (corregido)** | era falso → P2-01 |
| `/api/learning/activity` | `learning_queue`, `retrieval_safety_decisions`, `learning_retrieval_decisions`, `learning_evidence` | últimas N | fiable |
| `/api/runtime/metabolism/receipts` | `metabolic_receipts` | actual | fiable |
| `service_health` cola | `autonomous_tasks` (migrado en `e0105c2`) | actual | fiable |
| `HealthSensors._check_queue` | **`worker_tasks` (retirada)** | — | ciego → P3-01 |

**Tablas retiradas**: `worker_tasks` (última escritura 2026-07-29, retirada por
`019_legacy_retirement.sql`). Prohibido usarla como representación del estado
actual. Tras esta auditoría queda **un** consumidor: `_check_queue` (P3-01).

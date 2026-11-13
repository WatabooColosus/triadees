# PLAN TRÍADE Ω — POST MAIN

> Fecha: 2026-07-24
> Estado: En progreso
> Decisión de diseño: ViceVirtueState = wrapper retrocompatible, PlanningGraph = conectar existente, Causal Memory = sobre schema existente, Monitor = direct + psutil

---

## FASE 1 — Consolidación del Núcleo Cognitivo (P0)

### T-001: Hipotálamo PV-14

**Objetivo:** Elevar el Hipotálamo de regulador emocional básico a un regulador cognitivo completo con virtudes/vicios operativos, señales de hardware, y tensiones.

**Estado actual:**
- `triade/core/hypothalamus.py` (321 líneas): `Hypothalamus` class con `analyze()`, `apply_qualia_signals()`, `mood` property
- `triade/memory/hypothalamus_store.py` (379 líneas): `EmotionalState` (VAD + fatigue + pv7_baseline dict), `HypothalamusStateStore` (SQLite), pattern learning, reinforcement
- PV-7 virtudes como `dict[str, float]` en `EmotionalState.pv7_baseline`
- 8 emociones primarias: neutral, fatigued, engaged, anxious, calm, withdrawn, positive, cautious

**Lo que falta:**
1. ViceVirtueState class (wrapper retrocompatible sobre el dict pv7_baseline)
2. 7 pecados operativos (opuestos de las 7 virtudes)
3. Persistencia expandida del estado completo
4. Cálculo de tensiones (conflictos entre virtudes/vicios)
5. Decompayimiento temporal (fatiga cognitiva, no solo de runs)
6. Integración de señales CPU/RAM/GPU
7. Integración de señales del Scheduler
8. Integración de errores (Error Bus)
9. Carga cognitiva (cuánto está procesando el sistema)
10. Curiosidad (señal de exploración)
11. Fatiga detallada (por componente, no solo global)
12. Incertidumbre (nivel de confianza del sistema)

**Archivos a modificar:**
- `triade/core/hypothalamus.py` — Agregar sensores de hardware, scheduler, errores
- `triade/memory/hypothalamus_store.py` — Expandir EmotionalState, agregar tablas

**Archivos a crear:**
- `triade/hypothalamus/vice_virtue.py` — ViceVirtueState wrapper
- `triade/hypothalamus/senses.py` — SensesCPU, SensesRAM, SensesGPU, SensesScheduler, SensesErrors
- `triade/hypothalamus/cognitive_load.py` — Carga cognitiva, curiosidad, incertidumbre

**Migration:**
- `triade/memory/migrations/006_hypothalamus_pv14.sql` — Tablas expandidas

**Dependencias:**
- `psutil` para CPU/RAM
- `nvidia-smi` (subprocess) para GPU
- `triade/core/error_bus.py` para errores

---

### T-002: Cristal Qualia 2.0

**Objetivo:** Separar Qualia del Hipotálamo como sistema independiente. Crear QualiaPacket como contrato unificado. Agregar continuidad, significado, identidad, propósito.

**Estado actual:**
- `triade/qualia/` — 9 archivos: bus.py, router.py, store.py, state.py, contracts.py, adapters.py, introspection.py, reports.py, __init__.py
- `triade/core/qualia.py` (297 líneas): QualiaEngine con snapshot()
- `triade/core/crystal.py` (263 líneas): Crystal con regulate()
- Qualia está parcialmente integrada con Hypothalamus via `apply_qualia_signals()`

**Lo que falta:**
1. QualiaPacket como contrato unificado (actualmente usa 5 dataclasses separadas)
2. Continuidad entre runs (conexión temporal de experiencias)
3. Significado (qué implica cada experiencia para el sistema)
4. Identidad (cómo las experiencias moldean la identidad)
5. Propósito (cómo las experiencias se alinean con la misión)
6. Experiencias enriquecidas (contexto, relación con experiencias previas)
7. Memoria significativa (qué vale la pena recordar)
8. Detección de fragmentación (experiencias inconexas)
9. Persistencia de Qualia (ya existe en store.py pero puede necesitar expansión)

**Archivos a crear:**
- `triade/qualia/qualia_packet.py` — QualiaPacket dataclass unificado
- `triade/qualia/continuity.py` — Continuidad temporal entre experiencias
- `triade/qualia/meaning.py` — Cálculo de significado y propósito
- `triade/qualia/fragmentation.py` — Detección de fragmentación

**Archivos a modificar:**
- `triade/qualia/contracts.py` — Agregar QualiaPacket
- `triade/qualia/bus.py` — Integrar continuity y meaning
- `triade/core/crystal.py` — Integrar QualiaPacket
- `runner.py` — Actualizar flujo de Qualia

**Dependencias:**
- T-001 (ViceVirtueState para modulation)

---

### T-003: Central 2.0

**Objetivo:** Reemplazar la planificación textual por planificación estructurada con PlanStep, PlanGraph, dependencias, presupuestos, rollback, replanificación, delegación.

**Estado actual:**
- `triade/core/central.py` (562 líneas): Central con `plan()` que genera `PlanPacket` con `steps: list[str]` (texto plano)
- `triade/core/planning_graph.py` (246 líneas): PlanningGraph con GoalNode, dependencies, decompose, ready/blocked queries — **DEAD CODE, nunca importado**
- `triade/core/contracts.py`: PlanPacket (run_id, goal: str, steps: list[str], tools, safety_required)

**Lo que falta:**
1. PlanStep como dataclass estructurada (no string)
2. Integrar PlanningGraph existente a Central.plan()
3. SubGoals via PlanningGraph.decompose()
4. Dependencias via goal_dependencies
5. Presupuestos (tiempo, tokens, recursos por plan)
6. Prioridades en pasos
7. Rollback a nivel de plan (no solo regression)
8. Replanificación (detectar fallo → replanificar)
9. Delegación (Central delega a otros neuronas via plan)
10. Cierre del plan (marcar completion con métricas)
11. Persistencia del plan (ya existe via PlanningGraph SQLite)

**Archivos a crear:**
- `triade/core/plan_step.py` — PlanStep dataclass estructurada
- `triade/core/plan_budget.py` — Presupuestos de plan (tiempo, tokens, recursos)
- `triade/core/plan_rollback.py` — Rollback a nivel de plan
- `triade/core/replanification.py` — Detector de fallo + estrategia de replanificación

**Archivos a modificar:**
- `triade/core/central.py` — Integrar PlanStep + PlanningGraph + delegación
- `triade/core/contracts.py` — Actualizar PlanPacket para usar PlanStep
- `triade/core/planning_graph.py` — Conectar al runtime (no más dead code)

**Dependencias:**
- T-001 (ViceVirtueState para decisiones)
- T-002 (QualiaPacket para contexto)

---

### T-004: Integrador Cognitivo

**Objetivo:** Crear un módulo que integre Central + Hipotálamo + Cristal, aplique la Constitución, resuelva conflictos, y emita decisiones. NO crear otra IA — solo integración.

**Estado actual:**
- No existe un "Integrador Cognitivo" como clase
- La integración actual está dispersa en `runner.py` (900+ líneas)
- `constitution.py` (211 líneas): check_operation() solo verifica 3 de 10 artículos
- `safety.py` (158 líneas): Review de riesgo basado en keywords
- `response_governance.py` (286 líneas): Continuity + coherence + dedup

**Lo que falta:**
1. Integración Central ↔ Hipotálamo (señales的情绪 modulan planificación)
2. Integración Central ↔ Cristal (regulación ética del plan)
3. Integración Hipotálamo ↔ Cristal (emociones → regulación)
4. Aplicación automática de Constitución (10 artículos, no solo 3)
5. Resolución de conflictos (cuando Hipotálamo y Central discrepen)
6. Emisión de decisión (resultado integrado final)

**Archivos a crear:**
- `triade/core/cognitive_integrator.py` — IntegradorCognitivo class

**Archivos a modificar:**
- `triade/core/constitution.py` — Agregar enforcement para todos los artículos
- `runner.py` — Usar IntegradorCognitivo en vez de secuencial ad-hoc

**Dependencias:**
- T-001, T-002, T-003 (componentes integrados)

---

## FASE 2 — Bodega (P1)

### T-005: Memoria

**Objetivo:** Separar y tipificar todas las memorias como tipos de primer nivel.

**Estado actual (10 tipos):**
- Working Memory: `triade/consciousness/working_memory.py` (in-memory, max 10)
- Episodic: `schemas.sql` + Bodega methods
- Semantic (keyword): `schemas.sql` + Bodega LIKE search
- Semantic (vector): `semantic_store.py` + `semantic_search.py` + embeddings
- Identity (core): `schemas.sql` identity_core (inmutable)
- Identity (auto): `auto_identity_store.py` (evolving traits)
- Federated: `federated_nodes` + exchange/merge logs
- Emotional: `hypothalamus_store.py` (VAD + patterns)
- Procedural: Parcial (neuron definitions)
- Causal: Schema only (kg_nodes/kg_edges en migration 005)

**Lo que falta:**
- Social Memory (perfils de usuario, relaciones)
- System Memory (unificado, no disperso)
- Causal Memory (código Python sobre schema existente)
- Procedural Memory (dedicada, no solo neuron definitions)
- Working Memory persistente (actualmente RAM-only)

**Archivos a crear:**
- `triade/memory/causal_memory.py` — Módulo sobre kg_nodes/kg_edges
- `triade/memory/social_memory.py` — Perfiles de usuario/relaciones
- `triade/memory/system_memory.py` — Estado del sistema unificado
- `triade/memory/procedural_memory.py` — Conocimiento procedimental
- `triade/memory/working_memory_persistent.py` — Working memory con SQLite backup

**Migration:**
- `triade/memory/migrations/007_memory_expansion.sql`

---

### T-006: Consolidación

**Objetivo:** Completar el ciclo de consolidación: evidencia → confianza → versionado → historial → contradicciones → reemplazos → auditoría → compresión → olvido → restauración.

**Estado actual:**
- Evidence: `evidence_bridge.py` + `learning_evidence` table
- Confidence: Multi-nivel (memory, semantic, auto_identity, trust)
- Versioning: KnowledgeStateMachine + SemanticGovernance
- Contradictions: `contradiction_reports` + `kg_contradictions`
- Audit: `semantic_governance_events` + `knowledge_transitions`
- Forgetting: `forgetting_log` + decay_patterns
- Spaced Retrieval: SM-2 en `independent_evaluation.py`

**Lo que falta:**
- Compression (resumir episodios, deduplicar semántica)
- Restoration (restaurar olvidados, des-cuarentena)
- Reemplazos (tracking de qué reemplaza a qué)
- Historial completo unificado (scattered across tables)

**Archivos a crear:**
- `triade/memory/compression.py` — Compresión de memoria
- `triade/memory/restoration.py` — Restauración de olvidados
- `triade/memory/replacement_tracker.py` — Tracking de reemplazos

---

## FASE 3 — Neuronas (P1)

### T-007: Creadora

**Objetivo:** Corregir pipeline de la neurona Creadora. Agregar investigación, comparación, diseño, contratos, herramientas, tests, métricas, rollback.

**Estado actual:**
- `triade/neuron_factory/` — 8 archivos: Specification, Store, Candidate, Execution, Evaluation, Lifecycle, Exporter
- Pipeline: spec → candidate → execute → evaluate → lifecycle

**Lo que falta:**
- Research phase (investigar antes de crear)
- Comparison (comparar con soluciones existentes)
- Design (diseño antes de implementación)
- Contracts (contratos de entrada/salida)
- Tools registration (qué herramientas necesita)
- Tests (generar tests automáticamente)
- Metrics (métricas de calidad del output)
- Rollback (revertir creación fallida)

---

### T-008: Formadora

**Objetivo:** Agregar pipeline de entrenamiento completo.

**Estado actual:**
- `triade/neuron_factory/evaluation.py` — Evaluación básica
- `triade/neuron_factory/lifecycle.py` — Estados del ciclo de vida

**Lo que falta:**
- Dataset management
- Training episodes
- Benchmark execution
- Generalization testing
- Feedback loops
- Promotion/Degradation/Retirement automation

---

### T-009: Pipeline

**Objetivo:** Corregir pipeline de aprendizaje con sandbox, CI, canary, rollback, auditoría.

**Estado actual:**
- `triade/learning/pipeline.py` (698 líneas) — Pipeline completo con gates
- `triade/self_improvement/modification_pipeline.py` (281 líneas) — Mod lifecycle

**Lo que falta:**
- Sandbox integration en pipeline
- CI integration
- Canary deployment para cambios de aprendizaje
- Rollback automático en pipeline
- Auditoría expandida

---

## FASE 4 — Scheduler (P1)

### T-010: Scheduler

**Objetivo:** Integrar scheduler existente con prioridades, cuotas, heartbeat, leases, retry, circuit breaker, DLQ, persistencia, balanceo.

**Estado actual:**
- `triade/workers/scheduler.py` — Scheduler básico
- `triade/workers/task_queue.py` — Cola de tareas
- `triade/workers/adaptive_scheduler.py` — Adaptativo
- `triade/workers/lease_retry_breaker.py` — Lease + retry + circuit breaker (Fase 2 del plan anterior)

**Lo que falta:**
- Prioridades dinámicas
- Cuotas por tipo de tarea
- Heartbeat de workers
- Dead Letter Queue
- Balanceo de carga

---

### T-011: Workers

**Objetivo:** Completar ciclo de vida de workers.

**Estado actual:**
- `triade/workers/worker_loop.py` — Loop principal
- `triade/workers/background_service.py` — Servicio background
- `triade/workers/state_machine.py` — FSM de workers (Fase 2)

**Lo que falta:**
- Consumption tracking (cuántos recursos usa cada worker)
- Time tracking (tiempo por tarea)
- Owner tracking (quién creó la tarea)
- Restart automático
- Recovery post-fallo
- Supervisión en tiempo real

---

## FASE 5 — Herramientas (P1)

### T-012: Tool Registry

**Objetivo:** Completar tool registry con contratos, riesgo, timeouts, permisos, recursos, auditoría, versionado.

**Estado actual:**
- `triade/sandbox/tool_registry.py` — Registry con schemas básicos

**Lo que falta:**
- Contratos formales de herramientas
- Risk assessment por herramienta
- Timeouts configurables
- Permissions por herramienta
- Resource limits
- Audit trail
- Versioning

---

### T-013: Secure Executor

**Objetivo:** Completar executor con rootless, sandbox completo, replay, filesystem aislado, network policy, GPU/disk limits.

**Estado actual:**
- `triade/sandbox/secure_executor.py` — shell=False + forbidden patterns + SandboxLimits
- `triade/sandbox/isolation.py` — 3 niveles de aislamiento

**Lo que falta:**
- Rootless execution (unshare namespaces)
- Full sandbox (chroot/overlay)
- Replay recording (ya existe SandboxPolicy.record_execution)
- Filesystem isolation (bind mounts)
- Network policy (iptables/nftables)
- GPU limits (nvidia-cuda-mps-control)
- Disk limits (quota)

---

## FASE 6 — Aprendizaje (P1)

### T-014: Learning

**Objetivo:** Completar estados de aprendizaje + spaced repetition + causal learning + compresión.

**Estado actual:**
- Learning pipeline: candidate → evaluated → verified → validated_in_runs → consolidated
- Knowledge states: unknown → candidate → experimental → validated → stable → deprecated
- Spaced retrieval: SM-2 en independent_evaluation.py
- Forgetting: performance-based

**Lo que falta:**
- Causal learning (aprender relaciones de causa-efecto)
- Compression (resumir conocimiento acumulado)
- Estados deprecated/archived/retired más granulares

---

### T-015: Evaluación

**Objetivo:** Agregar benchmark execution, mutation testing, regression detection, quality metrics.

**Estado actual:**
- `triade/evaluation/runner.py` — Runner de evaluación
- `triade/evaluation/suites.py` — Suites de evaluación
- `triade/learning/independent_evaluation.py` — Evaluación independiente

**Lo que falta:**
- Benchmark execution automatizado
- Mutation testing integration
- Regression detection en tiempo real
- Quality metrics compuestas

---

## FASE 7 — Autoevolución (P2)

### T-016: Modification Pipeline

**Objetivo:** Integrar modification pipeline con TriadeOS.

**Estado actual:**
- `triade/self_improvement/modification_pipeline.py` — Lifecycle completo (proposed → ... → completed)

**Lo que falta:**
- TriadeOS integration (que TriadeOS invoque el pipeline automáticamente)

---

### T-017: Constitución

**Objetivo:** Aplicar constitución automáticamente a todos los componentes.

**Estado actual:**
- 10 artículos definidos, solo 3 enforced programáticamente (I, III, VI)

**Lo que falta:**
- Enforcement de artículos II, IV, V, VII, VIII, IX, X
- Integración automática en Central, Hipotálamo, Cristal, Bodega, Scheduler, Creadora, Formadora

---

## FASE 8 — Federación (P2)

### T-018: Federación

**Objetivo:** Completar federación multi-plataforma.

**Estado actual:**
- `triade/federation/` — 12 archivos: Exchange (HMAC), Edge Router, Evidence Gate, Peer Sync, etc.

**Lo que falta:**
- Android client
- PC client
- VPS deployment
- Cloud deployment
- Worker federation
- Trust Score expandido
- Resource sharing
- Replication

---

## FASE 9 — Recursos (P1)

### T-019: Monitor

**Objetivo:** Monitorear CPU, RAM, GPU, VRAM, disco, temperatura, red, modelos, scheduler, workers. Enviar señales al Hipotálamo.

**Estado actual:**
- `triade/core/resource_probe.py` — Probe básico
- Hardware: 8 CPU, 31GB RAM, Tesla T4 15GB

**Lo que falta:**
- Monitoreo completo de hardware
- Señales al Hipotálamo
- Temperature monitoring
- Network monitoring
- Model performance monitoring
- Scheduler/Worker health monitoring

**Implementación:**
- `psutil` para CPU/RAM/disk/network
- `nvidia-smi` (subprocess) para GPU/VRAM/temperature
- Integración directa (sin librerías externas pesadas)

---

## FASE 10 — Model Router (P1)

### T-020: Router

**Objetivo:** Selección automática de modelo según recursos, dificultad, costo, latencia.

**Estado actual:**
- `triade/core/model_router.py` — Router básico
- `triade/core/model_policy.py` — Políticas de modelo
- `triade/core/ollama_blood.py` — Health check de Ollama
- `triade/core/model_acquisition.py` — Adquisición de modelos

**Lo que falta:**
- Selección automática basada en:
  - Recursos disponibles (GPU memory, CPU load)
  - Dificultad de la tarea (simple → rápido, complejo → profundo)
  - Costo (tokens, latencia)
  - Historial de rendimiento por modelo

---

## FASE 11 — Dashboard (P2)

### T-021: Dashboard

**Objetivo:** Dashboard completo mostrando todos los subsistemas.

**Estado actual:**
- `apps/` — FastAPI app en puerto 8010
- `frontend/dist/` — React SPA pre-construida
- `apps/routes/api.py` — Endpoints básicos

**Lo que falta:**
- Endpoints para: Pulso, Hipotálamo, Central, Cristal, Bodega, Scheduler, Workers, Neuronas, Recursos, Aprendizaje, Federación
- Frontend components para cada subsistema

---

## FASE 12 — Autonomía 24/7 (P2)

### T-022: TriadeOS

**Objetivo:** Integrar definitivamente Supervisor + Scheduler + Creadora + Formadora + Learning + Pulso + Federación.

**Estado actual:**
- `triade/services/supervisor.py` (602 líneas) — Runtime 24/7
- `triade/os/` — TriadeOS, Event Engine, Neuron Scheduler, Knowledge Graph

**Lo que falta:**
- Integración completa de todos los subsistemas
- Ciclos autónomos configurables

---

### T-023: Rutinas Autónomas

**Objetivo:** Permitir que el sistema: aprenda, reorganice, investigue, cree neuronas, entrene, verifique, degradación, documente.

**Estado actual:**
- Background service ejecuta misiones periódicas
- Neuron factory permite crear neuronas
- Learning pipeline consolida conocimiento

**Lo que falta:**
- Rutinas de auto-mejora continua
- Creación autónoma de neuronas
- Entrenamiento autónomo
- Verificación autónoma
- Degradación autónoma
- Auto-documentación

---

## FASE 13 — Tríade Ω 1.0 (P0)

### T-024: Integración Final

**Objetivo:** Validar que todo funciona junto:
- Central planifica y coordina
- Hipotálamo regula estado interno y prioridades
- Cristal/Qualia mantiene identidad, continuidad y significado
- Bodega preserva y consolida conocimiento
- Creadora diseña nuevas capacidades
- Formadora entrena y evalúa
- Scheduler ejecuta trabajo continuo
- Constitución gobierna todas las decisiones críticas
- TriadeOS mantiene el sistema operativo autónomo

**Validaciones:**
- Test de integración completo
- Carga sostenida (24h mínimo)
- Recovery post-fallo
- Federación con al menos 2 nodos
- Dashboard funcional
- Todas las métricas verdes

---

## ORDEN DE EJECUCIÓN RECOMENDADO

```
FASE 1 (Núcleo Cognitivo) ─── FASE 1 PRIORIDAD MÁXIMA
  T-001 Hipotálamo PV-14     ← Primero: toda señal emocional fluye de aquí
  T-002 Cristal Qualia 2.0   ← Segundo: identidad y significado
  T-003 Central 2.0          ← Tercero: planificación estructurada
  T-004 Integrador Cognitivo ← Cuarto: une todo

FASE 9 + FASE 10 (Paralelo con Fase 1-3)
  T-019 Monitor              ← Necesario para Hipotálamo
  T-020 Router               ← Necesario para todo

FASE 2 (Bodega)
  T-005 Memoria              ← Expansión de tipos de memoria
  T-006 Consolidación        ← Compresión + restauración

FASE 3 (Neuronas)
  T-007 Creadora             ← Pipeline de creación
  T-008 Formadora            ← Pipeline de entrenamiento
  T-009 Pipeline             ← Integración de pipeline

FASE 4 (Scheduler)
  T-010 Scheduler            ← Integración completa
  T-011 Workers              ← Ciclo de vida de workers

FASE 5 (Herramientas)
  T-012 Tool Registry        ← Completar registry
  T-013 Secure Executor      ← Sandbox completo

FASE 6 (Aprendizaje)
  T-014 Learning             ← Estados + causal + compresión
  T-015 Evaluación           ← Benchmark + mutation testing

FASE 7 (Autoevolución)
  T-016 Modification Pipeline ← TriadeOS integration
  T-017 Constitución         ← Enforcement universal

FASE 8 (Federación)
  T-018 Federación           ← Multi-plataforma

FASE 11 (Dashboard)
  T-021 Dashboard            ← UI completa

FASE 12 (Autonomía)
  T-022 TriadeOS             ← Integración definitiva
  T-023 Rutinas Autónomas    ← Auto-mejora continua

FASE 13 (Integración)
  T-024 Integración Final    ← Validación completa
```

# ARCHITECTURE_MAP.md · Tríade Ω

Mapa de la arquitectura **tal como existe en el código** (no la visión). Estado al 2026-06-12, commit base `e597618`, frontera ≈ v2.1.

Leyenda de estado: 🟢 sólido · 🟡 parcial · 🔴 solo visión (sin código).

---

## 1. Vista de capas

```
                        ┌─────────────────────────────────────────────┐
   ENTRADAS             │  triade_digimon.py (CLI)   apps/*.py (FastAPI)│
                        │  run·chat·recall·doctor    api·chat_ui·single │
                        │  align·neuron·models       ·port·model_router │
                        │                            n8n/ (4 workflows) │
                        └───────────────────┬─────────────────────────┘
                                            │
                        ┌───────────────────▼─────────────────────────┐
   ORQUESTACIÓN         │        triade/core/runner.py · TriadeRunner   │
   (ciclo cognitivo)    │  input→señales→memoria→gobernanza→cristal→    │
                        │  plan→safety→salida→verificación→integridad   │
                        └──┬────┬────┬────┬────┬────┬────┬────┬─────────┘
                           │    │    │    │    │    │    │    │
        ┌──────────────────┘    │    │    │    │    │    │    └──────────────┐
        ▼                       ▼    │    ▼    │    ▼    │                   ▼
   Hypothalamus 🟢          Bodega 🟢│ Crystal🟢│ Safety🟢│            Verifier 🟢
   (PV-7, señales)         (SQLite)  │ (Q_crist)│(riesgo) │           (5 scores)
                                │    │         │         │
        ┌───────────────────────┘    │         │         │
        ▼                            ▼         ▼         ▼
   ÓRGANOS NÚCLEO            Central 🟡   contracts.py (paquetes tipados)
   triade/core/             (plan+resp)   config.py  alignment.py(estático D-03)
                            neuron_creator/trainer/registry 🟡 (FUERA del ciclo)
                                            │
                        ┌───────────────────▼─────────────────────────┐
   MEMORIA               │  triade/memory/  schemas.sql + migrations/   │
                         │  semantic_store · embedding_engine ·         │
                         │  semantic_search · semantic_governance(1.9E) │
                         │  ⚠ regresión 1.9F: list_documents (D-01/D-02)│
                         └───────────────────────────────────────────┬─┘
                                            │                         │
                        ┌───────────────────▼──────────┐   ┌──────────▼─────────┐
   MODELOS              │ triade/models/                │   │ SQLite triade.db   │
                         │ ollama_client · model_router  │   │ (16 tablas; 1      │
                         │ hardware_profile ·            │   │  "muerta": goals)  │
                        │ compatibility_matrix ·        │   └────────────────────┘
                        │ model_install_queue           │
                        │ → Ollama 127.0.0.1:11434 (opc)│
                        └───────────────────────────────┘
```

---

## 2. El ciclo cognitivo (runner.py, paso a paso)

| # | Paso | Órgano | Artefacto | Persistencia |
|---|---|---|---|---|
| 1 | Crear run | Bodega | `input.json` | tabla `runs` |
| 2 | Analizar señales (intención, PV-7, riesgo) | Hypothalamus | `signals.json` | `signal_states` |
| 3 | Recuperar memoria (identidad, episódica, semántica) | Bodega | `memory.json` | — |
| 4 | Gobernar memoria semántica (si recall on) | SemanticGovernance | (dentro de memory) | `semantic_governance_events` |
| 5 | Regular Cristal (Q_cristal + estado temporal contextual) | Crystal | `crystal.json` | `crystal_states` |
| 6 | Planear | Central | `plan.json` | — |
| 7 | Revisar Safety | Safety | `safety.json` | `knowledge_patterns` (domain=safety) |
| 8 | Responder (Ollama o fallback) | Central | `output.json` | `episodic_memory` |
| 9 | Registrar eventos/calidad de modelo | Bodega | `memory_diff.json` | `model_events` |
| 10 | Verificar | Verifier | `report.json` | `verification_reports` |
| 11 | Cerrar | Runner | `integrity.json` + `CLOSED` | `runs.status=closed` |

**Reglas duras implementadas:** no hay respuesta sin señales del Hipotálamo; el Cristal regula antes del plan; Safety revisa antes de salida; toda salida se verifica; todo run cierra con evidencia persistente.

---

## 3. Módulos por componente

### Neurona Central 🟡
- `core/central.py` — `Central.plan()`, `Central.respond()`. Regulación por `q_crystal`/`temporal_status`, prompts con atribución literal.
- `core/neuron_creator.py` — **N Creadora**: `NeuronCreator.create() → NeuronSpec`.
- `core/neuron_trainer.py` — **N Formadora**: `NeuronTrainer.evaluate() → NeuronTrainingResult` (estados candidate/experimental/stable/rejected).
- `core/neuron_registry.py` — persistencia en tablas `neurons` / `neuron_training`.
- ⚠ **Desconexión:** estos tres últimos solo se usan vía CLI `neuron`, no en `run()`.

### Hipotálamo Emocional 🟢
- `core/hypothalamus.py` — `Hypothalamus.analyze() → SignalPacket`. PV-7 (humildad, generosidad, respeto, paciencia, templanza, caridad, diligencia). Modelo+fallback por reglas con validación JSON.

### Bodega de Almacenamiento 🟢
- `core/bodega.py` — persistencia y recall, `doctor`, migración Crystal v2.
- `memory/semantic_store.py` — documentos + embeddings + protección de estado gobernado. ⚠ D-01/D-02.
- `memory/semantic_embedding_engine.py` — vectorización vía Ollama (1.9B). ⚠ usa `list_documents(limit=)`.
- `memory/semantic_search.py` — similitud coseno (1.9C). ⚠ `dict(metadata)`.
- `memory/semantic_governance.py` — gobierno de estados y cuarentena (1.9E). ⚠ `doctor()` usa `list_documents(limit=)`.
- `memory/schemas.sql` (16 tablas) + `memory/migrations/001_9A_semantic_memory.sql`.

### Cristal Morfológico 🟢
- `core/crystal.py` — `Crystal.regulate()`: ética/profundidad/creatividad/relación, `pv7_score`, `stability`, `intensity`, fórmula `Q_cristal` relacional (s_h/s_t/s_rel/φ_memory), estado temporal contextualizado (baseline/stable/improving/degrading/critical). ⚠ D-06 (método legacy duplicado).

### Safety 🟢
- `core/safety.py` — `Safety.review()`. Estados: approved / approved_with_warning / requires_human_approval / blocked. ⚠ `sandbox_only` declarado, no emitido (D-09).

### Verification 🟢
- `core/verification.py` — `Verifier.verify() → VerificationReport` (coherencia, memoria, safety, utilidad, trazabilidad).

### QualiaBus 🟢
- `triade/qualia/` — contratos, router, store, state, bus, adapters y reportes.
- Convierte `NeuronExperience` en `QualiaSignal`, `CentralKnowledgePacket`, `StorageMemoryPacket` y candidato LearningPipeline opcional.
- Persistencia: `qualia_experiences`, `qualia_signals`, `qualia_central_packets`, `qualia_storage_packets`, `qualia_states`.
- Integración: Runner genera artefactos `qualia_*.json`; Central consume resumen autorizado; Hipotálamo modula señales internas; Bodega reporta en doctor; CLI/API `qualia`.
- Política: hipótesis y candidatos, no memoria estable; nada toca `identity_core`.

### Neuron Contributions 🟢 (Fase 2.1)
- `triade/core/contracts.py` — `NeuronContributionPacket`, `NEURON_STATUS_EFFECTS`, `IDENTITY_CORE_FORBIDDEN_EFFECTS`.
- Estados de neurona y efectos permitidos:
  - `candidate` → observe, diagnose
  - `experimental` → + propose_learning
  - `active_assistant` → + influence_plan
  - `trusted_worker` → + influence_response, write_experimental_memory
  - `stable` → + request_stable_promotion
- `triade/core/experimental_neuron_runtime.py` — produce `NeuronContributionPacket` por cada activación, filtrado por estado.
- `triade/core/run_neuron_orchestrator.py` — extrae contributions, genera candidatos de aprendizaje, agrega a memory_diff/system_events.
- `triade/core/runner.py` — `_process_neuron_contributions()` filtra por risk != critical, confidence >= 0.60, Safety, y identity_core safety.
- Resultado del run incluye: neuronas activadas, contributions usadas, ignoradas, bloqueadas, razón.
- Regla innegociable: ninguna neurona puede modificar `identity_core`.

### Living Workers 🟢
- `triade/workers/` — scheduler, task_queue, worker_loop, background_service, state_store. Ejecuta ciclos acotados y auditables en `runs/background/`.
- 10 task types: pulse_check, pending_learning_review, semantic_memory_governance, neuron_candidate_formation, experimental_neuron_activity, neuron_autopromotion, federation_inbox_review, memory_consolidation_review, stable_consolidation_review, system_debt_scan.
- memory_consolidation_review marca candidatos verified como `used_in_run` (no consolida directamente).
- stable_consolidation_review consolida solo candidatos `validated_in_runs` con evidencia suficiente.
- Persistencia: `worker_tasks`, `worker_runs`, `worker_events`, `worker_state`.
- Superficies: CLI `workers once/start/daemon/status/stop/queue/events/doctor` y endpoints `/workers/*`.
- Política: no modifica identity_core, no escribe memoria stable sin evidencia, no red externa por defecto, no shell arbitrario.

### Learning Pipeline 🟢 (Fase C)
- `triade/learning/pipeline.py` (`LearningPipeline`) sobre `learning_queue`:
  `candidate → evaluated → verified → validated_in_runs → consolidated | rejected | archived`.
- `mark_used_in_run(candidate_id, run_id, outcome_score)` registra uso en runs; auto-promueve a `validated_in_runs` tras 3 usos con promedio >= 0.70.
- Consolidación exige: verified o validated_in_runs, source_ref, risk != critical, run_use_count >= 3, avg_outcome_score >= 0.70.
- Consolidación vía gobernanza semántica 1.9E (candidate→experimental→stable). Nunca toca `identity_core`. CLI `learn`. Tests en `tests/test_learning_pipeline.py`.

### Federation 🟢 (Fase D)
- `triade/federation/federation.py` (`Federation`): registro de nodos (permisos/confianza/estado), recepción gated (autenticación → permiso → Safety → log → Learning Pipeline como candidato), envío con bloqueo de fuga de datos, revocación.
- Permisos prohibidos por defecto (modify_identity_core, write_stable_memory, …) rechazados al registrar. Nada recibido se consolida automáticamente. CLI `federate`. Tests en `tests/test_federation.py`.

### Capa de Modelos (transversal) 🟢
- `models/ollama_client.py` — health, generate, embed.
- `models/model_router.py` — selección por rol/intención/urgencia/hardware con fallback.
- `models/hardware_profile.py` — detección de tier (low/medium/high).
- `models/compatibility_matrix.py`, `models/model_install_queue.py` — matriz de compatibilidad y cola de instalación.

### Contratos (transversal) 🟢
- `core/contracts.py` — dataclasses: InputPacket, SignalPacket, MemoryPacket, CrystalPacket, PlanPacket, SafetyPacket, OutputPacket, VerificationReport.

---

## 4. Esquema SQLite (`schemas.sql` — 29 tablas)

| Tabla | Usada por código | Estado |
|---|---|---|
| `identity_core` | Bodega (recall identidad) | 🟢 activa (semilla: entity_name, misión, ética, origen) |
| `runs` | Bodega | 🟢 activa |
| `episodic_memory` | Bodega | 🟢 activa |
| `semantic_memory` | Bodega `_search_semantic` | 🟡 activa pero vacía |
| `neurons` | NeuronRegistry (CLI) | 🟡 activa solo vía CLI |
| `neuron_activity` | neuron_activity_store, experimental_neuron_evidence, qualia/adapters | 🟢 activa |
| `neuron_training` | NeuronRegistry (CLI) | 🟡 activa solo vía CLI |
| `signal_states` | Bodega | 🟢 activa |
| `crystal_states` (+22 cols migradas v2) | Bodega/Crystal | 🟢 activa |
| `learning_queue` | LearningPipeline (Fase C) | 🟢 activa |
| `knowledge_patterns` | Bodega (safety + patrones) | 🟢 activa |
| `model_events` | Bodega | 🟢 activa |
| `verification_reports` | Bodega/Verifier | 🟢 activa |
| `trust_levels` | trust_store, life_pulse | 🟢 activa |
| `reinforcement_log` | hypothalamus_store, trust_store | 🟢 activa |
| `federated_nodes` | Federation (Fase D) | 🟢 activa |
| `federated_exchange_log` | Federation (Fase D) | 🟢 activa |
| `goals` | consciousness/salience | 🟢 activa (baja actividad) |
| `qualia_experiences` | QualiaBus | 🟢 activa |
| `qualia_signals` | QualiaBus | 🟢 activa |
| `qualia_central_packets` | QualiaBus | 🟢 activa |
| `qualia_storage_packets` | QualiaBus | 🟢 activa |
| `qualia_states` | QualiaBus | 🟢 activa |
| `worker_tasks` | Living Workers | 🟢 activa |
| `worker_runs` | Living Workers | 🟢 activa |
| `worker_events` | Living Workers | 🟢 activa |
| `worker_state` | Living Workers | 🟢 activa |
| `hypothalamus_state` | hypothalamus_store, consciousness | 🟢 activa |
| `auto_identity` | auto_identity_store, bodega, life_pulse | 🟢 activa |

*Nota:* `triade.db` está en `.gitignore` (correcto); la única DB versionada es `backups/triade-before-systemd.db` (24 runs, 14 ciclos cristal/señal/safety/verificación, 10 eventos de modelo; todas las tablas activas).

---

## 5. Superficies de entrada

| Superficie | Archivo | Rol |
|---|---|---|
| CLI | `triade_digimon.py` | run, chat, recall, doctor, align, api, neuron, models, qualia, workers |
| API principal | `apps/api_app.py` | `/triade/run`, `/recall`, `/doctor`, `/neurons*` (con API key) |
| App unificada | `apps/single_port_app.py` | chat + semántica + router + run en un puerto |
| Chat UI | `apps/chat_ui_app.py`, `apps/chat_ui_router_app.py` | UIs web (⚠ duplicación, D-07) |
| Model Router API | `apps/model_router_api.py` | `/health`, `/models/doctor` |
| Orquestación | `n8n/*.json` | webhook, chat producción, neuron create/list |

---

## 6. Resumen de madurez por órgano (medido, no autoreportado)

```
Runner       ████████░░  sólido      — ciclo completo verificado end-to-end
Bodega       ████████░░  sólido      — SQLite real, persistencia auditable
Hypothalamus ███████░░░  operativo   — PV-7 + señales + fallback
Verification ███████░░░  operativo   — 5 scores, retroalimentación
Safety       ███████░░░  operativo   — 4/5 estados (falta sandbox_only)
Crystal      ███████░░░  operativo   — Q_cristal + temporal contextual
Central      ██████░░░░  parcial     — N Creadora/Formadora fuera del ciclo
Semántica    ████████░░  operativa   — regresión 1.9F reparada (Fase A.1)
Learning     ███████░░░  operativo   — pipeline Fase C sobre learning_queue
Federation   ███████░░░  operativo   — nodos + intercambio gated (Fase D)
Workers      ██████░░░░  operativo   — ciclos locales acotados, auditables y seguros
QualiaBus    ███████░░░  operativo   — experiencias neuronales circulan como señales/paquetes/candidatos
```

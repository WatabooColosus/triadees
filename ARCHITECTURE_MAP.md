# ARCHITECTURE_MAP.md · Tríade Ω

Mapa de la arquitectura **tal como existe en el código** (no la visión). Estado al 2026-06-12, commit base `e597618`, frontera ≈ v2.1.

> **Corrección 2026-07-30 (auditoría por-órgano con evidencia de call sites,
> no reafirmación del texto anterior):** varias afirmaciones de este mapa
> quedaron obsoletas por cambios reales del propio proyecto entre el
> 2026-06-12 y hoy. Ver notas inline marcadas `[VERIFICADO 2026-07-30]` y el
> detalle completo en `TECHNICAL_DEBT.md` § "Fase 2 — auditoría por órgano".
> Resumen de lo que cambió: (1) N Creadora/Formadora/Registry **sí** están
> dentro del ciclo automático (runner + 24/7), la nota de "desconexión" de
> la sección 3 era falsa incluso en `e597618`; (2) la duplicación D-07
> (`chat_ui_app.py`/`chat_ui_router_app.py`/`api_app.py`/`model_router_api.py`)
> fue eliminada por el propio proyecto en el commit `aa001f3` (2026-07-29),
> consolidada en `apps/single_port_app.py` + `apps/routes/*`; esos archivos
> ya no existen.

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
- `core/central.py` — `Central.plan()`, `Central.respond()`. Regulación por `q_crystal`/`temporal_status`, prompts con atribución literal. Llamadas reales en `runner.py:453,504,544,548,554`.
- `core/neuron_creator.py` — **N Creadora**: `NeuronCreator.create() → NeuronSpec`.
- `core/neuron_trainer.py` — **N Formadora**: `NeuronTrainer.evaluate() → NeuronTrainingResult` (estados candidate/experimental/stable/rejected).
- `core/neuron_registry.py` — persistencia en tablas `neurons` / `neuron_training`.
- ✅ **[VERIFICADO 2026-07-30] CONECTADAS, no "fuera del ciclo":** las tres
  se invocan vía `primary_neuron_pipeline.py` → `runner.py:1394`
  (`_propose_neuron_candidate`, activo por defecto en `run()`) y también
  desde el ciclo 24/7 (`neuron_formation_pipeline.py` ← `worker_loop.py:1408`
  y `life_pulse.py`). `NeuronRegistry` además se expone en
  `apps/routes/api.py:699,725,3068,3091`.
- 🔴 **Código muerto confirmado:** `Central.execute_plan_steps()`,
  `save_plan()`, `load_plan()` y las clases `PlanGraph`/`PlanStep`/
  `StepBudget` no tienen ningún caller productivo. Su único consumidor,
  `triade/runtime/governed_plan_dispatcher.py` (`GovernedPlanDispatcher`),
  a su vez no tiene ningún caller fuera de su propio archivo — huérfano por
  partida doble.

### Hipotálamo Emocional 🟢
- `core/hypothalamus.py` — `Hypothalamus.analyze() → SignalPacket`. PV-7 (humildad, generosidad, respeto, paciencia, templanza, caridad, diligencia). Modelo+fallback por reglas con validación JSON.
- **[VERIFICADO 2026-07-30]** conectado solo al ciclo por-run (`runner.py:222,326`), no corre dentro del ciclo 24/7 (`supervisor.py`/`workers/*` no lo invocan) — coherente con ser un regulador de tono conversacional, no un chequeo de fondo.

### Bodega de Almacenamiento 🟢
- `core/bodega.py` — persistencia y recall, `doctor`, migración Crystal v2. **[VERIFICADO 2026-07-30]** conectada a ambos ciclos: `runner.py:227` (por-run) y `supervisor.py:539,562` + `worker_loop.py:1787` (24/7).
- `memory/semantic_store.py` — documentos + embeddings + protección de estado gobernado. ⚠ D-01/D-02 → **[VERIFICADO 2026-07-30] YA CORREGIDO**: `list_documents(limit=)` (semantic_store.py:270) tiene la firma correcta y todos los call sites la usan bien; esta advertencia quedó obsoleta (la línea 217 de este mismo doc ya lo decía, pero no se limpiaron estas notas ⚠).
- `memory/semantic_embedding_engine.py` — vectorización vía Ollama (1.9B). 🔴 **[VERIFICADO 2026-07-30] código muerto:** `embed_pending()` (línea 310) no tiene ningún caller fuera de su propia clase/tests.
- `memory/semantic_search.py` — similitud coseno (1.9C). Conectada: `bodega.py:65` la invoca dentro del flujo real de `runner.py`.
- `memory/semantic_governance.py` — gobierno de estados y cuarentena (1.9E). Conectada: `runner.py:438` la ejecuta en cada run. ⚠ **[VERIFICADO 2026-07-30]** en `worker_loop.py:1684-1685` se instancian `SemanticMemoryStore`/`SemanticMemoryGovernance` dentro del ciclo 24/7 sin invocar ningún método — construcción vestigial sin efecto, "por estar".
- `memory/schemas.sql` (16 tablas) + `memory/migrations/001_9A_semantic_memory.sql`.

### Cristal Morfológico 🟢
- `core/crystal.py` — `Crystal.regulate()`: ética/profundidad/creatividad/relación, `pv7_score`, `stability`, `intensity`, fórmula `Q_cristal` relacional (s_h/s_t/s_rel/φ_memory), estado temporal contextualizado (baseline/stable/improving/degrading/critical). ⚠ D-06 (método legacy duplicado).
- ⚠ **[VERIFICADO 2026-07-30]** solo conectado al ciclo por-run (`runner.py:230,449`). El ciclo 24/7 (`worker_loop.py:1268-1269`) **no llama a `Crystal.regulate()`**: construye un `CrystalPacket` estático (`temporal_status="stable"` fijo) solo para satisfacer el chequeo de `Safety.review()`. La regulación real de Cristal nunca opera fuera de conversaciones — los ciclos de fondo (workers) corren con un Cristal "de mentira".

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
- ⚠ **[VERIFICADO 2026-07-30]** son **19 task types reales**, no 10 — el
  README subestima la lista. A los 10 documentados (pulse_check,
  pending_learning_review, semantic_memory_governance,
  neuron_candidate_formation, experimental_neuron_activity,
  neuron_autopromotion, federation_inbox_review, memory_consolidation_review,
  stable_consolidation_review, system_debt_scan) se suman 9 sin documentar:
  `bodega_global_review`, `goal_research`, `goal_safe_command`,
  `research_curriculum`, `goal_install`, `goal_lora_train`,
  `encrypted_backup`, `neuron_education_cycle`,
  `write_governed_text_artifact` (`triade/workers/contracts.py:22-30`,
  `worker_loop.py:914-922`). Los 19 handlers hacen trabajo verificable real
  (SQL, efectos con receipt/rollback); ninguno es un no-op.
- memory_consolidation_review marca candidatos verified como `used_in_run` (no consolida directamente).
- stable_consolidation_review consolida solo candidatos `validated_in_runs` con evidencia suficiente.
- Persistencia: `worker_tasks`, `worker_runs`, `worker_events`, `worker_state`.
- Superficies: CLI `workers once/start/daemon/status/stop/queue/events/doctor` y endpoints `/workers/*`.
- Política: no modifica identity_core, no escribe memoria stable sin evidencia, no red externa por defecto, no shell arbitrario.
- 🔴 **[VERIFICADO 2026-07-30] código muerto dentro de `triade/workers/`:**
  `state_machine.py` (`WorkerStateMachine`) y `lease_retry_breaker.py`
  (`Lease`, `CircuitBreaker`, etc.) — cero referencias en todo el repo,
  incluyendo tests. `advanced_scheduler.py` y `worker_supervisor.py` sí se
  importan, pero solo para `.doctor()` en paneles de salud
  (`triade/dashboard/routes.py`, `system_monitor.py`) — no forman parte del
  loop 24/7 real (`worker_autostart.py` → `WorkerBackgroundService` →
  `WorkerLoop` usa `scheduler.py`/`adaptive_scheduler.py`/`task_queue.py`).

### Learning Pipeline 🟢 (Fase C)
- `triade/learning/pipeline.py` (`LearningPipeline`) sobre `learning_queue`:
  `candidate → evaluated → verified → validated_in_runs → consolidated | rejected | archived`.
- `mark_used_in_run(candidate_id, run_id, outcome_score)` registra uso en runs; auto-promueve a `validated_in_runs` tras 3 usos con promedio >= 0.70.
- Consolidación exige: verified o validated_in_runs, source_ref, risk != critical, run_use_count >= 3, avg_outcome_score >= 0.70.
- Consolidación vía gobernanza semántica 1.9E (candidate→experimental→stable). Nunca toca `identity_core`. CLI `learn`. Tests en `tests/test_learning_pipeline.py`.
- ✅ **[VERIFICADO 2026-07-30]** las 4 transiciones tienen un caller
  productivo real (no solo tests): `pending_learning_review` (worker),
  `stable_consolidation_review` (worker), y `mark_used_in_run` vía
  `run_learning_usage.py:194` ← `runner.py:1043` en cada run. ⚠ El estado
  real que produce `verify()` es `internally_checked`, no `verified` como
  dice el nombre de la transición en este documento. ⚠ La transición
  `internally_checked → validated_in_runs` exige que el productor del run
  adjunte `learning_outcome_score` + `learning_outcome_evidence_ref`
  explícitos en `memory_diff`; si no lo hace, el uso queda en
  `observed_not_counted` y nunca cuenta — **pendiente confirmar si algo en
  producción popula esos campos hoy**, o si esta transición es real-pero-
  rara-vez-disparada en la práctica (ver `TECHNICAL_DEBT.md`).

### Federation 🟢 (Fase D)
- `triade/federation/federation.py` (`Federation`): registro de nodos (permisos/confianza/estado), recepción gated (autenticación → permiso → Safety → log → Learning Pipeline como candidato), envío con bloqueo de fuga de datos, revocación.
- Permisos prohibidos por defecto (modify_identity_core, write_stable_memory, …) rechazados al registrar. Nada recibido se consolida automáticamente. CLI `federate`. Tests en `tests/test_federation.py`.
- ✅ **[VERIFICADO 2026-07-30]** `federation_inbox_review` corre de verdad en
  el ciclo 24/7 (`worker_loop.py:1664-1678`), pero solo hace un chequeo de
  estado local (`federation.doctor()` sobre `federated_exchange_log`) — el
  propio handler devuelve `"external_network": False`. El router de
  federación (`apps/routes/api.py:2177-2387`) sí está montado en
  `single_port_app.py`, alcanzable en producción.
- 🔴 **[VERIFICADO 2026-07-30] código muerto:** `triade/federation/merge.py`
  (`FederatedMerge`) ni siquiera está exportado en `federation/__init__.py`.
  `dispatch.py` y `evidence_gate.py` se exportan pero no tienen importadores
  reales fuera de tests.

### Entrenamiento LoRA/PEFT 🟢 (no cubierto en versiones previas de este mapa)
- `triade/training/{governed_lora,lora_trainer,installer,peft_canary,serving_governance}.py`.
- ✅ **[VERIFICADO 2026-07-30]** Cadena real y activa, no solo declarada:
  `POST /api/governance/lora/jobs` (`apps/routes/governance.py:105-118`,
  montado en `single_port_app.py`) → `goal_orchestrator.schedule_lora` →
  task `goal_lora_train` (`worker_loop.py:1151-1156`) →
  `GovernedLoraJobRunner.run` → `RealLoraTrainer.train` (PEFT/torch real,
  exige CUDA). Evidencia en DB real (no test): 2 filas en `trainable_adapters`
  con `adapter_sha256` y artefacto `.safetensors` en disco; 2 eventos de
  canary con texto generado real y latencia medida
  (`scripts/run_phase_13_lora_canary.py`, no un test).
- Gate de aprobación humana **sí bloquea de verdad** en código (no solo en
  docs): `governed_lora.py:23-24`, `peft_canary.py:133-166`,
  `serving_governance.py:133-146` — sin `approved_by` no vacío, estado
  `blocked` antes de tocar disco/GPU. `lora_trainer.py:259-262` marca
  explícitamente `"automatic_activation": False`; nada activa un adaptador
  automáticamente tras entrenar.
- ⚠ Conectado pero **nunca ejercitado en producción**: `governed_peft_active_slot`
  y `peft_serving_state` tienen 0 filas — la activación/rollback en serving
  nunca se disparó fuera de una prueba deliberada de que el bloqueo funciona.
- Caveat de seguridad real: el gate de aprobación solo exige una cadena
  `approved_by` no vacía; no valida identidad humana verdadera (RBAC/firma)
  — el carácter "nominal" de la aprobación depende de quién tenga la API key.

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

> **[VERIFICADO 2026-07-30]** `apps/api_app.py`, `apps/chat_ui_app.py`,
> `apps/chat_ui_router_app.py`, `apps/ui_html.py` y `apps/model_router_api.py`
> **ya no existen** — eliminados en el commit `aa001f3` (2026-07-29),
> consolidados en `apps/single_port_app.py` + `apps/routes/{api,ui,auth,
> governance,health}.py`. La tabla de abajo refleja lo que corre hoy, no la
> tabla original de este documento.

| Superficie | Archivo | Rol | Quién la arranca |
|---|---|---|---|
| CLI | `triade_digimon.py` | run, chat, recall, doctor, align, api, neuron, models, qualia, workers | manual |
| App unificada gobernada | `apps/single_port_app.py` (monta `governance_router`, `auth_router`, `health_router`, `api_router`, `ui_router`) | chat + semántica + router + run + UI React en un puerto | `deploy/systemd/triade-api.service` (puerto 8010, este entorno), `Dockerfile.cloud` + `compose.free.yml`/`compose.cloud.yml` |
| Relay público | `apps/public_relay_app.py` vía `apps/public_relay_entrypoint.py` | `/api/register`, `/api/heartbeat`, `/api/jobs*` para nodos federados/Android | `Procfile`, `railway.json`, `render.yaml`, `Dockerfile` (Railway/Render, puerto `$PORT`) — superficie de producción real y **distinta** de single_port_app, no huérfana |
| Emparejamiento de federación | `apps/federation_pairing_app.py` | pairing manual de nodos | nada la arranca en ningún deploy config; solo tiene test — herramienta manual, no servicio persistente |
| Agente nodo móvil | `apps/mobile_node_agent.py` | agente Python para ejecutar en el propio dispositivo (Termux/Android) | ejecución manual del usuario, no un servicio de este servidor |
| Orquestación | `n8n/*.json` | webhook, chat producción, neuron create/list | n8n externo |

### Nodo Android (`android/triade-node/`) — real, no aspiracional

**[VERIFICADO 2026-07-30]** No es un esqueleto vacío: 6 archivos Java reales
(1296 líneas) — `AndroidModelRuntime.java`, `MainActivity.java`,
`RelayClient.java`, `TriadeNodeService.java`, `NodeConfig.java`,
`TextPreprocessor.java` — más binarios `.so` de llama.cpp/ggml para
inferencia local embebida. `RelayClient.java` hace llamadas HTTP reales a
`/api/register`, `/api/heartbeat`, `/api/federation/transport/{next,result}`,
`/api/jobs/{id}/result`, endpoints que existen literalmente en
`apps/routes/api.py` y `apps/public_relay_app.py`. Lo que falta probar (y
coincide con `TECHNICAL_DEBT.md`) es una federación sostenida entre dos hosts
físicos distintos usando este cliente real, no que el cliente sea falso.

### `systemd/` (carpeta raíz) — legado, riesgo de colisión

**[VERIFICADO 2026-07-30]** Distinto de `deploy/systemd/` (única fuente real
instalada y verificada en este servidor). Las unidades de `systemd/` apuntan
a `WorkingDirectory=/home/santiago/triadees`, `User=santiago` — una máquina
distinta a este entorno. `systemd/triade-model-router.service` dice
literalmente en su `Description`: "DEPRECATED — merged into
single_port_app:8010". `systemd/triade.service` y `triade-chat-ui.service`
usan el mismo `ExecStart` que `deploy/systemd/triade-api.service`: si
alguna vez se instalaran juntas colisionarían en el puerto 8010. Riesgo real:
el commit más reciente del repo (`aa001f3`, autor "Triade Evolution Worker",
un worker autónomo) todavía tocó `systemd/triade-ollama.service` y
`systemd/triade.service` — es decir, un proceso autónomo del propio sistema
sigue escribiendo en la carpeta legado. Recomendado marcarla `DEPRECATED`
explícitamente o eliminarla, para que ningún proceso autónomo futuro la
instale por error.

---

## 6. Resumen de madurez por órgano (medido, no autoreportado)

```
Runner       ████████░░  sólido      — ciclo completo verificado end-to-end
Bodega       ████████░░  sólido      — SQLite real, persistencia auditable
Hypothalamus ███████░░░  operativo   — PV-7 + señales + fallback
Verification ███████░░░  operativo   — 5 scores, retroalimentación
Safety       ███████░░░  operativo   — 4/5 estados (falta sandbox_only)
Crystal      ███████░░░  operativo   — Q_cristal + temporal contextual
Central      ██████░░░░  parcial     — N Creadora/Formadora SÍ conectadas (ver 3); execute_plan_steps/GovernedPlanDispatcher muertos
Semántica    ████████░░  operativa   — regresión 1.9F reparada (Fase A.1)
Learning     ███████░░░  operativo   — pipeline Fase C sobre learning_queue
Federation   ███████░░░  operativo   — nodos + intercambio gated (Fase D)
Workers      ██████░░░░  operativo   — ciclos locales acotados, auditables y seguros
QualiaBus    ███████░░░  operativo   — experiencias neuronales circulan como señales/paquetes/candidatos
```

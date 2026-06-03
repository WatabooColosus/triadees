# ARCHITECTURE_MAP.md · Tríade Ω

Mapa de la arquitectura **tal como existe en el código** (no la visión). Estado al 2026-06-02, commit base `90c548f`, frontera ≈ v1.9F.

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
                        │ ollama_client · model_router  │   │ (16 tablas; 4      │
                        │ hardware_profile ·            │   │  "muertas": ver §4)│
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

### Learning Pipeline 🟢 (Fase C)
- `triade/learning/pipeline.py` (`LearningPipeline`) sobre `learning_queue`:
  `candidate → evaluated → verified → consolidated | rejected | archived`.
- Consolidación vía gobernanza semántica 1.9E (candidate→experimental→stable). Nunca toca `identity_core`. CLI `learn`. Tests en `tests/test_learning_pipeline.py`.
- Pendiente: enganche automático con `run()` (aprendizaje post-run) y sandbox real.

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

## 4. Esquema SQLite (`schemas.sql` — 16 tablas)

| Tabla | Usada por código | Estado |
|---|---|---|
| `identity_core` | Bodega (recall identidad) | 🟢 activa (semilla: entity_name, misión, ética, origen) |
| `runs` | Bodega | 🟢 activa |
| `episodic_memory` | Bodega | 🟢 activa |
| `signal_states` | Bodega | 🟢 activa |
| `crystal_states` (+22 cols migradas v2) | Bodega/Crystal | 🟢 activa |
| `verification_reports` | Bodega/Verifier | 🟢 activa |
| `knowledge_patterns` | Bodega (safety + patrones) | 🟢 activa |
| `model_events` | Bodega | 🟢 activa |
| `neurons` / `neuron_training` | NeuronRegistry (CLI) | 🟡 activa solo vía CLI |
| `semantic_memory` (keyword legacy) | Bodega `_search_semantic` | 🟡 activa pero vacía |
| `semantic_documents` / `semantic_embeddings` / `semantic_governance_events` (migración 1.9A/1.9E) | capa semántica | 🟡 activa, con regresión 1.9F |
| `learning_queue` | LearningPipeline (Fase C) | 🟢 activa |
| `federated_nodes` | Federation (Fase D) | 🟢 activa |
| `federated_exchange_log` | Federation (Fase D) | 🟢 activa |
| `goals` | — | 🔴 muerta (única restante) |

*Nota:* `triade.db` está en `.gitignore` (correcto); la única DB versionada es `backups/triade-before-systemd.db` (24 runs, 14 ciclos cristal/señal/safety/verificación, 10 eventos de modelo; tablas muertas en 0).

---

## 5. Superficies de entrada

| Superficie | Archivo | Rol |
|---|---|---|
| CLI | `triade_digimon.py` | run, chat, recall, doctor, align, api, neuron, models |
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
```

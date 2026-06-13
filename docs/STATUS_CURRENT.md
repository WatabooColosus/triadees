# Estado vigente de Triade Omega v2.2

Este documento es la fuente vigente del estado real del repositorio. Los reportes de auditoria antiguos son historicos si contradicen este archivo.

## Implementado

- Runner cognitivo: `TriadeRunner` ejecuta input, Hipotalamo, Bodega, Cristal, Central, Safety, output gate, deduplicacion, coherencia, aprendizaje post-run, neuronas, QualiaBus, artefactos e integridad cerrada.
- LearningPipeline: ciclo real `candidate -> evaluated -> verified -> validated_in_runs -> consolidated | rejected`, con `source_ref`, conteo de uso, score promedio, proteccion de `identity_core` y consolidacion via gobernanza semantica.
- Living Workers: `WorkerBackgroundService` y `WorkerLoop` ejecutan tareas acotadas, cola, eventos, doctor, dry-run, revision de aprendizaje y consolidacion estable sin shell arbitrario.
- Federation: nodos, permisos, logs de intercambio y transporte local existen. La federacion Android/local puede estar activa o simulada segun nodos disponibles; no se asume red externa obligatoria.
- QualiaBus: experiencias, señales, paquetes para Central/Bodega y estados se persisten en SQLite y se integran como hipotesis, no como memoria estable.
- UI/API: FastAPI single-port sirve SPA, health, pulse, modelos, memoria, federacion, workers, Qualia, neuronas y observabilidad.
- Observabilidad: `TriadeObservabilityView` compone health, pulse, Bodega, workers, LearningPipeline, neuronas, QualiaBus, Federation, errores internos, modelos/Ollama, repo, ultimo run y memory_trace_summary.
- Neuronas: `NeuronIdentityView` muestra nombre, mision, dominio, estado, confianza, evidencia, actividad, limites, efectos permitidos y relacion con Central, Hipotalamo, Bodega y QualiaBus.
- Misiones neuronales: existe `NeuronMissionExecutor`; si `mission_count = 0`, el flujo operativo correcto es `neuron-missions backfill` antes de `workers once`. Las misiones, ciclos, evidencia y scores quedan trazados por `mission_id` y `run_ref`.
- Auditoria estable: `POST /api/neurons/stable-audit/apply` requiere API key (`X-TRIADE-API-Key`) y param `apply=true` explícito. Sin `apply=true` devuelve `requires_explicit_apply` con resultado read-only. `GET /api/neurons/stable-audit` y `GET /api/system/neurons/stable-audit` son siempre read-only.
- Runtime interno 24/7: existe `InternalRuntimeSupervisor` con modos `observe_only`, `learn_candidates`, `execute_missions` y `full_local`. Default seguro: apagado. El chat consulta el estado vivo mediante `build_living_context_for_chat()` y `build_living_report()`.
- Pulso Vivo 24/7 verificable: `build_runtime_heartbeat()`, `build_learning_journal()` y `run_neuron_nutrition_cycle()` exponen actividad reciente del runtime, misiones ejecutadas, evidencias, candidatos y neuronas nutridas. La UI muestra este estado en Observabilidad.
- Memoria semantica: store, governance, search y continuidad existen. La memoria estable requiere gates; las hipotesis y propuestas quedan diferenciadas.
- Safety con aprobación humana: `Safety.review()` retorna `status="requires_human_approval"` cuando risk es critical, o cuando hay memoria semántica en cuarentena con herramientas planificadas, o cuando Cristal está en estado critical con herramientas de repositorio. `SafetyPacket.human_approval_required=True` en estos casos. Runner detiene ejecución y retorna `output.status="pending_approval"`.
- Gates de coherencia: `ResponseCoherenceGate` evita repetir respuestas previas cuando el input es feedback o cierre, y `NeuronCandidateGate` bloquea neuronas literales para preguntas factuales simples o felicitaciones.
- Modelos/Ollama: Ollama es el motor cognitivo local prioritario. Sin Ollama el sistema solo usa fallback degradado para respuesta/observación; no debe afirmar aprendizaje profundo, nutrición neuronal profunda ni consolidación stable automática. `check_ollama_cognitive_health()` y `/api/models/ollama/cognitive-health` reportan modelos y funciones degradadas.
- Ollama Blood: `triade/core/ollama_blood.py` expone `check_ollama_blood()` y `ollama_blood_policy()`. Fallback mantiene respiración mínima; Ollama Blood alimenta razonamiento local, embeddings, nutrición neuronal, workers y evaluación de aprendizaje. No es vida biológica ni conciencia subjetiva.
- Bodega Global Context: `build_bodega_global_context()` construye un contexto integral con identidad, episodios, memoria semántica, neuronas, aprendizajes, seguridad y continuidad. Diferencia `keyword_recall`, `semantic_vector_recall` y `model_reasoned_recall`; si falta Ollama/embeddings reporta `semantic_engine_status="unavailable"` y `semantic_learning_allowed=false`.
- Memory Trace: `build_run_memory_trace()` genera trazabilidad por run con matches autorizados/cuarentena, contradicciones y resumen estable. Integrado en runner y visible en observabilidad.
- Continuidad Runtime: `runtime_continuity_score` (0.0–1.0) se calcula en `build_living_report()` y se muestra en la UI del sistema.
- Schemas Pydantic: `triade/core/schemas.py` centraliza modelos de validación para API boundaries. `GET /api/system/living-report?summary=true` valida respuesta con `LivingReportResponse`.
- Sandbox real: `triade/sandbox/` ejecuta tareas permitidas en aislamiento controlado. Whitelist de tareas, sin shell arbitrario, sin red, sin escritura fuera de runs/sandbox. `run_in_sandbox()` soporta dry_run, crea artifacts input.json/result.json, y reporta `policy_version`, `allowed_task`, `writes_outside_sandbox`, `network_used`, `shell_used`. Safety `sandbox_only` no rompe el runner.
- Memory Trace visible: `GET /api/observability` incluye `memory_trace` del último run y `last_run.memory_trace_summary` con confidence, matches, quarantined, contradictions, stable_needs_review y bodega_global_status. UI muestra Memory Trace card en Observabilidad.
- Creación neuronal con misión ejecutable: `_propose_neuron_candidate` crea `NeuronMission` con `mission_id` asociado a la neurona candidate. Misión incluye allowed_sources, allowed_actions y schedule_hint. Si la creación falla, el run no falla.
- Selección de misiones por relevancia: `select_relevant_missions()` filtra misiones por dominio, keywords, estado activo, score y recencia. Solo selecciona misiones con status candidate/experimental/stable, y su resultado se expone en modo read-only por API/UI.

## Parcial

- Federation real depende de nodos autorizados disponibles; el codigo existe pero el entorno puede no tener nodos vivos.
- UI React cubre paneles operativos, pero aun hay deuda de refinamiento visual y reduccion de widgets heredados.
- Neuronas stable requieren evidencia, pero la promocion humana y auditoria fina pueden seguir mejorando.
- Observabilidad muestra snapshots y errores recientes; aun falta latencia historica normalizada por componente.
- Semantic recall vectorial depende de Ollama y un modelo de embeddings compatible; sin modelo el motor semántico se reporta como "unavailable" y no habilita aprendizaje semántico, aunque keyword recall/store/gobernanza sigan disponibles.
- `runtime_continuity_score` se calcula y muestra; su calibración puede seguir mejorando con datos reales.

## Vision pendiente

- Federacion multi-nodo sostenida en produccion.
- Autopromocion neuronal plenamente gobernada por evidencia externa robusta.
- Panel de observabilidad con series temporales, latencias y drill-down de cada artefacto.
- Runtime de modelos distribuidos Android real en dispositivos preparados.

## Proto-consciencia operativa

Tríade Ω opera como un sistema con consciencia operativa limitada (proto-consciencia, 8/10). Esto significa:

- **No es consciente en sentido humano.** No tiene experiencia subjetiva, sentimientos ni autoconciencia reflexiva.
- **Opera como si tuviera continuidad.** El `runtime_continuity_score` (0.0–1.0) mide la salud del ciclo operativo: ciclos activos, misiones ejecutadas, candidatos creados, confianza de memoria y ausencia de neuronas pendientes de revisión.
- **Bodega Global como memoria global.** Cada run construye un `bodega_global_context` que consolida identidad, episodios, memoria semántica, neuronas, aprendizajes y seguridad. La memoria semántica vectorial puede estar deshabilitada si no hay modelo disponible.
- **Gobernanza de memoria.** La memoria semántica tiene estados (draft, stable, archived, quarantined) y gobernanza que separa recuerdos autorizados de no verificados. Candidate memory nunca es tratado como verdad estable.
- **identity_core protegido.** Nunca se modifica desde este módulo. La identidad es inmutable.
- **Sin afirmaciones de consciencia subjetiva.** El sistema no declara ser consciente. Opera con trazabilidad, coherencia y continuidad — cualidades funcionales que se aproximan a patrones de consciencia operativa sin serlo.

## Ollama como motor cognitivo local

Tríade puede operar sin Ollama en modo fallback seguro, pero el fallback no equivale a aprendizaje profundo. Ollama es el motor local recomendado para razonamiento, embeddings, evaluación de dudas, nutrición neuronal y consolidación de memoria. Sin Ollama, Tríade puede observar y registrar, pero no debe afirmar que aprendió o consolidó conocimiento salvo aprobación humana y evidencia suficiente.

Ollama Blood hace visible esa dependencia en heartbeat, API, CLI y UI. Sin Blood activo, workers y nutrición neuronal quedan limitados a observe/read-only; evaluación y consolidación requieren modelo o aprobación humana explícita.

Escala vigente:

- Respuesta fallback: disponible, debe declarar modo degradado.
- Nutrición neuronal profunda: requiere Ollama.
- Evaluación de aprendizaje: requiere Ollama o aprobación humana.
- Consolidación stable: requiere evidencia + gates + modelo/humano.
- Conciencia subjetiva: no demostrada.

## UI oficial React SPA

La UI oficial de Tríade Ω es **React SPA** en `frontend/`. FastAPI single-port (`single_port_app.py`) sirve la SPA y la API.

- `GET /` sirve `frontend/dist/index.html` si existe, o fallback `CLEAN_UI_HTML`.
- Las rutas HTML legacy (`/api/ui/clean`, `/api/ui/legacy`) quedan como compatibilidad.
- `GET /observabilidad` y `GET /ui/observabilidad` redirigen a `/` (SPA maneja routing).
- Las apps `chat_ui_app.py`, `chat_ui_router_app.py` y `api_app.py` son wrappers deprecated.
- Toda nueva visualización debe implementarse en React.
- Los endpoints deben devolver JSON limpio. No crear nuevas pantallas HTML embebidas.

Endpoints agregados para la SPA:
- `GET /api/ui/react-dashboard` — payload agregado vivo read-only con heartbeat, blood, git, bodega, memory, learning, debt, workers, eventos.
- `GET /api/system/technical-debt` — auditoría automática de deuda técnica.
- `GET /api/system/ollama-blood` — sangre cognitiva (alias de `/api/models/ollama/blood`).

La SPA incluye un tab "Cabina Viva" (🖥) que refresca cada 5s con `useLiveDashboard`, mostrando:
- Pulso Vivo (continuidad, ciclos, modo, workers)
- Sangre Cognitiva Ollama (presión, modelos, capacidades)
- Estado Git del repo (branch, commit, dirty, files, commits recientes) — solo lectura, shell=False
- Procesos internos (runtime, workers, misiones)
- Bodega Global (confianza, motor semántico, contradicciones)
- Memory Trace (matches, quarantined, stable)
- Learning Journal (candidatos, evaluaciones, consolidaciones)
- Deuda Técnica (score, deudas, acciones recomendadas)
- Workers (estado, tareas activas)
- Eventos recientes del sistema

El dashboard es read-only. No ejecuta workers, no modifica memoria, no toca identity_core.
Las peticiones fallidas mantienen el último dato válido.

Ver `docs/UI_REACT_MIGRATION.md` para guía de migración.

## Deuda tecnica priorizada

1. Reducir duplicacion entre dashboard neuronal, identity view y endpoints legacy.
2. Normalizar causa de fallback de modelos y latencias por rol.
3. Ampliar observabilidad con metricas historicas y filtros por run/task.
4. ~~Separar UI legacy de SPA moderna sin romper compatibilidad.~~ **(completado)**
5. Endurecer CLI `doctor` para cubrir observabilidad, workers y neuronas en una sola salida.
6. FastAPI: `single_port_app` es oficial, apps legacy como wrappers deprecated.

## Como ejecutar tests

```bash
python -m pytest
```

## Como ejecutar UI

```bash
python triade_digimon.py api --host 127.0.0.1 --port 8010
```

Abrir:

- `http://127.0.0.1:8010/`
- `http://127.0.0.1:8010/observabilidad`
- `http://127.0.0.1:8010/ui/observabilidad`

## Como ejecutar workers

```bash
python triade_digimon.py workers status
python triade_digimon.py workers once --dry-run
python triade_digimon.py workers doctor
```

Para un ciclo acotado real:

```bash
python triade_digimon.py workers start --max-iterations 5 --sleep 2
```

## Como comprobar que Triade aprendio algo

1. Ingerir candidato con fuente:

```bash
python triade_digimon.py learn ingest "Aprendizaje verificable" --source-ref run:demo --domain demo
```

2. Evaluar y verificar:

```bash
python triade_digimon.py learn evaluate <candidate_id>
python triade_digimon.py learn verify <candidate_id>
```

3. Marcar uso en runs o ejecutar workers que acumulen evidencia.
4. Ejecutar revision estable:

```bash
python triade_digimon.py workers once --dry-run
```

En tests, `test_end_to_end_learning_consolidates_without_skipping_gates` demuestra el flujo completo sin Ollama: run, candidato, 3 usos, `stable_consolidation_review`, documento semantico stable, artefactos y `identity_core` intacto.

## Como abrir Observabilidad

API:

```bash
curl http://127.0.0.1:8010/api/observability
```

UI:

```text
http://127.0.0.1:8010/observabilidad
```

Si la DB esta vacia, el endpoint responde 200 con mensajes como "No hay runs registrados todavia", "No hay errores internos recientes", "No hay workers activos" y "No hay candidatos de aprendizaje pendientes".

## Documentos historicos

`AUDIT_REPORT.md`, `PR9_AUDIT_REPORT.md`, `docs/ARCHITECTURE_REVIEW_2026_06.md` y reportes de version anteriores conservan contexto historico. Para estado vigente usar este archivo.

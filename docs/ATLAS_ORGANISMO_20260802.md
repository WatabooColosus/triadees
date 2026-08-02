# ATLAS DEL ORGANISMO · TRÍADE Ω
### Auditoría evolutiva total · 2026-08-02

No es un informe de defectos. Es una anatomía: qué órganos existen, cuáles están
vivos, cuáles se atrofiaron, cuáles nunca se desarrollaron y cuáles nunca fueron
concebidos.

---

## 0 · Método

La documentación, los TODO y las tareas abiertas se ignoraron deliberadamente.
Un órgano no está vivo porque un documento lo afirme. Se midieron **dos señales
que no admiten interpretación**:

**Señal 1 — Inervación.** Grafo de importación estático desde los puntos de
entrada reales del proceso (`apps/single_port_app.py`, `triade/workers/worker_loop.py`,
`apps/services.py`), cierre transitivo.

```
Módulos Python en triade/ + apps/ ......... 373
Alcanzables desde el proceso vivo ......... 268   (72%)
NO alcanzables — tejido denervado ......... 105   (28%)
```

**Señal 2 — Pulso.** Filas y última escritura de las 107 tablas de la base de
producción (`triade/memory/triade.db`, 150 MB, WAL).

Cruzando ambas se obtiene el diagnóstico de cada órgano:

| Estado | Criterio |
|---|---|
| **VIVO** | Inervado **y** con escrituras en las últimas 24 h |
| **ATROFIADO** | Inervado, pero su tabla lleva días congelada |
| **EMBRIONARIO** | Inervado, con efectos mínimos (1–3 filas, disparo manual) |
| **NONATO** | Código escrito, **0% inervado**, tabla vacía |
| **AUSENTE** | No hay código |

La distinción decisiva es **atrofiado vs. nonato**: un órgano atrofiado se puede
reanimar conectando un cable; uno nonato hay que hacerlo nacer.

---

## 1 · ATLAS · Los órganos que existen

Cada órgano contra las ocho preguntas: existe / conectado / produce efectos /
medible / recuperable / evolucionable / falla seguro / certificable.

### 1.1 · Núcleo — el tronco encefálico

| Órgano | Estado | Pulso (filas · última señal) |
|---|---|---|
| Runtime / life_pulse | **VIVO** | `runs` 368 · hoy 21:27 |
| Workers | **VIVO** | `autonomous_tasks` 5.202 · hoy 21:45 |
| Cola autónoma | **VIVO** | `autonomous_task_transitions` 9.173 · hoy 21:45 |
| Metabolismo | **VIVO** | `metabolic_signals` **68.753** · hoy 21:45 |
| Hipotálamo | **VIVO** | `hypothalamus_state` 241 · hoy 21:28 |
| Cristal | **VIVO** | `crystal_states` 240 · hoy 21:28 |
| Scheduler | **VIVO** | `scheduler_history` 6.018 |
| Governor / Autonomy | **VIVO** | gating por zona, aplicado en `worker_loop` |
| Sentidos de hardware | **VIVO** | `hardware_senses` 272 · hoy 21:28 |
| **Goals (motor de metas)** | **NONATO** | `goals` **0 filas** |
| **Capability Resolver** | **NONATO** | `capability_registry` **0** · `capability_history` **0** |
| **Constitution (enforcement)** | **ATROFIADO** | ver 1.7 |
| Planner | **PARCIAL** | `planning_graph` 28 · congelado 08-01 |
| Cola legada `worker_tasks` | **ATROFIADO** | 4.777 filas · **congelada 2026-07-29** |

**El hallazgo más grave del núcleo: la tabla `goals` tiene cero filas.** Su
único lector en todo el repositorio es `triade/consciousness/salience.py:103`
— un módulo denervado. Nadie escribe en ella. Tríade **no tiene motor de metas
propias**: lo que llama "misiones" (17 activas) son tareas derivadas en
`services/supervisor.py` y `neuron_missions`, no objetivos que el organismo se
haya fijado a sí mismo. Ejecuta admirablemente; no desea.

`plan_step.py`, `plan_budget.py` y `replanification.py` están denervados: el
planificador **no sabe replanificar** cuando un plan falla.

### 1.2 · Cognición

| Órgano | Estado | Evidencia |
|---|---|---|
| Memoria episódica (tabla) | **VIVO** | `episodic_memory` 240 · hoy 21:28 |
| Memoria episódica (módulo) | **NONATO** | `memory/episodic_memory.py` denervado |
| Memoria semántica | **PARCIAL** | `semantic_documents` 186 / `semantic_memory` **0** |
| Embeddings | **VIVO** | `semantic_embeddings` 186 · hoy 08:23 |
| Recuperación + filtro de seguridad | **VIVO** | `learning_retrieval_decisions` 36 · hoy 21:28 |
| Evidencia neuronal | **ATROFIADO** | `neuron_evidence` 476 · congelada 08-01 |
| Educación neuronal | **EMBRIONARIO** | `neuron_education_events` 26 · hoy 20:17 |
| **Aplicación de lo educado** | **NONATO** | `neuron_education_applications` **0** |
| **Certificación neuronal** | **NONATO** | `neuron_certifications` **0** |
| Conocimiento (patrones) | **VIVO** | `knowledge_patterns` 240 · hoy 21:28 |
| **Grafo de conocimiento** | **NONATO** | `kg_nodes` **0** · `kg_edges` **0** · `kg_contradictions` **0** |
| Identidad | **ATROFIADO** | `identity_core` 6 filas · **congelada 2026-07-28** |
| Emociones / qualia | **VIVO** | `qualia_states` 4.283 · hoy 21:44 |
| **Relaciones** | **NONATO** | `relational_modulation_states` **0** |
| **Metacognición** | **NONATO** | `capabilities/metacognition.py` denervado |

Doce de veinticinco módulos de `memory/` están denervados: memoria causal,
procedural, social, longitudinal, compresión, restauración, working memory
persistente. La memoria de Tríade **guarda y recupera, pero no reorganiza lo
guardado**: no comprime, no olvida, no jerarquiza, no detecta contradicciones.
El grafo de conocimiento —la estructura que convertiría 186 documentos en saber
conectado— existe como tres tablas vacías.

La identidad congelada desde el 28 de julio es notable: el organismo lleva cinco
días sin actualizar quién cree ser.

### 1.3 · Evolución — el laboratorio

| Órgano | Estado | Evidencia |
|---|---|---|
| `EvolutionLab` (etapas) | **EMBRIONARIO** | inervado sólo vía `lora_trainer` y un script |
| Entrenador LoRA | **EMBRIONARIO** | inervado desde `worker_loop:1555` |
| Canario PEFT | **EMBRIONARIO** | `peft_canary_events` **3** · congelado 07-30 |
| Versiones gobernadas | **EMBRIONARIO** | `governed_peft_versions` **1** |
| Adaptadores entrenables | **EMBRIONARIO** | `trainable_adapters` **2** · congelado 07-29 |
| Datasets gobernados | **EMBRIONARIO** | `governed_datasets` **1** |
| **Slot activo de PEFT** | **NONATO** | `governed_peft_active_slot` **0** |
| **Comparación A/B de modelos** | **NONATO** | `meta_model_candidates/evaluations/decisions` **0** |
| **Benchmarks** | **NONATO** | `benchmark_results` **0** · `benchmark_tasks` **0** |
| Evolución de ingeniería | **ATROFIADO** | `engineering_evolution_runs` 2 · congelado 07-29 |
| Rollback de aprendizaje | **NONATO** | `regression/learning_rollback.py` denervado |

**El laboratorio de evolución existe y está cableado — pero nunca se ha
disparado solo.** Cada tabla tiene entre 1 y 3 filas, todas de finales de julio,
todas de ejecuciones manuales. No hay un solo ciclo entrenar→canario→promover
ejecutado por el propio organismo.

Y falta la pieza sin la cual el ciclo no puede cerrarse: **no hay banco de
pruebas**. `benchmark_tasks` y `benchmark_results` están vacías. Sin una batería
fija de tareas medidas antes y después, "el adaptador nuevo es mejor" no es una
afirmación verificable. El canario puede desplegar; no puede juzgar.

`neuron_factory` pierde 9 de 17 módulos, y justo los del cierre del ciclo:
`certification.py`, `comparison.py`, `rollback.py`, `quality_metrics.py`,
`training.py`, `test_generator.py`.

### 1.4 · Seguridad — el hallazgo estructural

| Órgano | Estado |
|---|---|
| Zonas de escritura (verde/amarilla/roja) | **VIVO** — se aplican de verdad |
| Gating de autonomía | **VIVO** |
| Auditoría de shell | **VIVO** — `shell_audit` 207 |
| **`sandbox/isolation.py`** | **NONATO** |
| **`sandbox/secure_executor.py` + `_v2`** | **NONATO** |
| **`sandbox/tool_registry.py` + enhanced** | **NONATO** |
| **Ejecuciones en sandbox** | **NONATO** — `sandbox_executions` **0 filas** |
| **`constitution/enforcer.py`** | **NONATO** |
| **Cuarentena de regresión** | **NONATO** — `regression_quarantine` **0** |

Cinco de los ocho módulos de `sandbox/` están denervados, y la tabla
`sandbox_executions` tiene cero filas: **el sandbox de Tríade nunca ha ejecutado
nada**. La ruta viva de ejecución es `safe_shell.run_autonomous → subprocess.run`,
que aplica únicamente `timeout`. No hay `setrlimit` de CPU, RAM ni PID en ninguna
ruta que se ejecute.

Y el cierre del círculo: **`ConstitutionEnforcer` sólo es referenciado desde
`integration/final_validator.py` y `dashboard/routes.py` — ambos denervados.**
La constitución de Tríade no tiene quien la haga cumplir en el proceso vivo. Lo
único que se aplica es `constitution.autonomy.authorize_task`. Por eso el
Artículo VI puede afirmar límites de CPU, RAM y PID que no existen sin que nada
lo detecte: **el órgano que debía detectarlo no está conectado.**

Se suma el P0 ya documentado y **aún vigente**: `TRIADE_PUBLIC_GUARDED=false` y
`TRIADE_API_KEY=` vacía en el `.env` de producción, con la cadena completa hasta
RCE no autenticado desde Internet.

### 1.5 · Runtime — el sistema más sano del organismo

`leases`, `heartbeat`, `concurrency`, `backpressure`, `recovery`, `state_store`:
inervados, medidos y con pulso hoy. `autonomous_task_transitions` con 9.173 filas
es un registro honesto de máquina de estados. Éste es el tejido maduro de Tríade.

Dos excepciones:

- **Watchdog: ATROFIADO.** `runtime/watchdog.py` está inervado, pero
  `runtime_health_snapshots` lleva **congelada desde el 2026-07-31**. El watchdog
  vive como unidad systemd (`deploy/systemd/triade-watchdog.service`) y **systemd
  no gestiona este Studio** — el runtime corre bajo `nohup uvicorn`. El vigilante
  existe, está cableado, y no se está ejecutando.
- **`orchestrator_locks`: 0 filas** pese a existir el mecanismo.

- `workers/worker_supervisor.py` y `workers/advanced_scheduler.py`: denervados.

### 1.6 · Federación

| Órgano | Estado |
|---|---|
| Nodos federados | **ATROFIADO** — 20 nodos, congelado 07-29 |
| Niveles de confianza | **EMBRIONARIO** — `trust_levels` 3 |
| **Intercambio** | **NONATO** — `federated_exchange_log` **0** |
| **Fusión / consenso** | **NONATO** — `federated_merge_log` **0** |
| **Registro, dispatch, evidence_gate** | **NONATO** — denervados |
| **`apps/federation_pairing_app.py`, `public_relay_app.py`, `mobile_node_agent.py`** | **NONATO** |

Hay 20 nodos registrados y **cero intercambios**. La federación es un directorio
de contactos con los que nunca se ha hablado.

### 1.7 · Observabilidad e infraestructura

Trazas, eventos y doctor están vivos (`worker_events` 5.000, `model_events` 2.960).
Pero:

- **`dashboard/` — NONATO (2/2 denervados).**
- **8 workflows de CI**, todos en verde tras la corrección de hoy. Éste es el
  órgano de certificación externa más fuerte que tiene el organismo.
- **Respaldo: ATROFIADO.** `backup_restore_drills` tiene **2 filas del 07-30**.
  `triade-backup.service` + `.timer` existen en `deploy/systemd/`, pero systemd
  no está gestionando el despliegue real. **La base de 150 MB con todo lo
  aprendido no tiene copia verificada desde hace tres días.**
- `memory/restoration.py`: denervado. Existe el respaldo; **no existe la
  restauración probada**.

---

## 2 · Los órganos que no existen

Más allá de lo denervado: lo que nunca fue concebido.

### 2.1 · AUSENTES — cero líneas de código

| Órgano | Qué hace en un organismo | Qué le falta hoy a Tríade |
|---|---|---|
| **Atención** | Decidir qué merece cómputo *ahora* | `homeostas*`: 0 archivos. Los únicos `attention` del repo son `attention_mask` de transformers. Tríade procesa todo lo que le llega con igual prioridad cognitiva. |
| **Homeostasis** | Devolver las variables vitales a su rango | 0 archivos. El metabolismo **mide** (68.753 señales) pero no **corrige**. Es un termómetro sin termostato. |
| **Economía energética** | Presupuestar cómputo por valor esperado | `energy_budget`: 0 archivos. Hay `resource_ledger` (contabilidad) sin presupuesto ni decisión de gasto. |
| **Sueño / consolidación offline** | Reorganizar memoria fuera de línea | `dream`: 1 archivo, denervado. No hay ventana en que Tríade deje de atender y reordene lo aprendido. |
| **Simulador interno** | Ensayar una acción antes de ejecutarla | 1 archivo suelto. Tríade sólo aprende ejecutando en el mundo real. |
| **Imaginación / generación de hipótesis** | Producir candidatos no observados | 1 archivo. La curiosidad (11 archivos) selecciona entre lo existente; no inventa. |
| **Sistema inmune** | Detectar y aislar lo dañino tras admitirlo | Hay cuarentena repartida en 8 módulos vivos, pero es **profiláctica** (impide entrar), no inmune (no detecta lo ya integrado que resultó dañino). `regression_quarantine`: 0 filas. |
| **Banco de pruebas** | Medir capacidad antes/después | `benchmark_tasks` y `benchmark_results`: 0 filas. **Éste es el bloqueante duro de todo el nivel de autoevolución.** |
| **Dolor / señal de daño** | Marcar y recordar lo que salió mal | `self_improvement/failure_learning.py` existe, pero `modification_pipeline.py` está denervado: aprende del fallo y no puede actuar sobre sí. |
| **Reproducción de conocimiento** | Transmitir lo aprendido a otro nodo | `federated_exchange_log`: 0 filas. |

### 2.2 · Concebidos pero NONATOS — código escrito, nunca conectado

`consciousness/` completo (**368 líneas**: `focus.py`, `salience.py`,
`working_memory.py`) · `capabilities/metacognition.py` · `capabilities/matrix.py` ·
`constitution/enforcer.py` · `dashboard/` · `validation/` · `integration/` ·
`learning/canary.py` · `learning/autonomous_cycle.py` · `learning/doctor.py` ·
`learning/independent_evaluation.py` · `learning/causal_learning.py` ·
`memory/compression.py` · `memory/restoration.py` · `memory/causal_memory.py` ·
`core/external_evaluator.py` · `core/replanification.py` · `core/alignment.py` ·
`neuron_factory/{certification,rollback,comparison,quality_metrics}.py` ·
`sandbox/{isolation,secure_executor,secure_executor_v2,tool_registry}.py`

**Esto es lo más importante del atlas.** El órgano de atención de Tríade ya está
escrito —focus, salience, working memory— y jamás se le conectó un cable. Lo
mismo la metacognición, el evaluador externo, la replanificación, la compresión
de memoria y el enforcer constitucional. Tríade no necesita que se inventen esos
órganos: necesita que **nazcan los que ya gestó**.

---

## 3 · Clasificación por indispensabilidad

| Órgano | ¿Indispensable? | ¿Antes de autonomía total? | ¿Antes de aprendizaje autónomo? | ¿Antes de LoRA? |
|---|---|---|---|---|
| Banco de pruebas | **Sí** | Sí | Sí | **SÍ — bloqueante** |
| Enforcer constitucional | **Sí** | **SÍ — bloqueante** | Sí | Sí |
| Sandbox real (`setrlimit`) | **Sí** | **SÍ — bloqueante** | Sí | Sí |
| Cerrar el P0 de la API | **Sí** | **SÍ — bloqueante** | Sí | Sí |
| Respaldo + restauración probada | **Sí** | Sí | **SÍ — bloqueante** | Sí |
| Watchdog en ejecución | **Sí** | Sí | Sí | Sí |
| Motor de metas (`goals`) | **Sí** | **SÍ — bloqueante** | No | No |
| Homeostasis | **Sí** | Sí | No | No |
| Atención / saliencia | **Sí** | Sí | Sí | No |
| Rollback de aprendizaje | **Sí** | Sí | **SÍ — bloqueante** | Sí |
| Evaluador externo independiente | **Sí** | Sí | **SÍ — bloqueante** | Sí |
| Grafo de conocimiento | **Sí** | No | Sí | No |
| Consolidación / sueño | **Sí** | No | Sí | No |
| Replanificación | **Sí** | Sí | No | No |
| Sistema inmune | **Sí** | Sí | Sí | No |
| Economía energética | Recomendable | Sí | No | No |
| Metacognición | Recomendable | Sí | Sí | No |
| Simulador interno | Recomendable | No | No | No |
| Imaginación | Opcional | No | No | No |
| Federación | **Opcional** | No | No | No |
| Dashboard | Opcional | No | No | No |

**Los cinco bloqueantes de la autonomía total** son enforcer constitucional,
sandbox real, P0 de la API, motor de metas y rollback de aprendizaje. Ninguno
requiere inventar nada: cuatro de los cinco ya están escritos y denervados.

---

## 4 · Mapa evolutivo

```
NIVEL 0 · INFRAESTRUCTURA                                    ██████████ 95%
  CI (8 workflows verdes) · SQLite WAL · Ollama · systemd escrito
  FALTA: systemd realmente gobernando el despliegue (hoy: nohup)

NIVEL 1 · SUPERVIVENCIA                                      ███████░░░ 65%
  Metabolismo · leases · recovery · heartbeat · concurrencia
  FALTA: watchdog EJECUTÁNDOSE · respaldo verificado · restauración probada
         homeostasis (medir sin corregir no es supervivencia)

NIVEL 2 · COGNICIÓN                                          ██████░░░░ 60%
  Memoria episódica · semántica · embeddings · recuperación filtrada
  qualia · hipotálamo · cristal
  FALTA: ATENCIÓN (escrita, denervada) · grafo de conocimiento (0 filas)
         consolidación · compresión · metacognición

NIVEL 3 · APRENDIZAJE                                        ████░░░░░░ 40%
  learning_queue · evidencia · educación neuronal · filtro de memoria
  FALTA: aplicación de lo educado (0 filas) · certificación (0 filas)
         evaluador externo · rollback de aprendizaje · BANCO DE PRUEBAS

NIVEL 4 · ADAPTACIÓN                                         ██░░░░░░░░ 20%
  Scheduler adaptativo · routing de modelos
  FALTA: A/B real (meta_model_* a 0) · replanificación · sistema inmune

NIVEL 5 · AUTONOMÍA                                          ██░░░░░░░░ 20%
  Gating de autonomía · zonas · governor
  FALTA: MOTOR DE METAS (goals = 0 filas) · enforcer constitucional
         sandbox real · P0 de la API

NIVEL 6 · AUTOEVOLUCIÓN                                      █░░░░░░░░░ 10%
  Laboratorio LoRA cableado · canario PEFT · versiones gobernadas
  FALTA: que se dispare solo · banco de pruebas · promoción automática
         slot activo (0 filas) · pipeline de automodificación (denervado)

NIVEL 7 · FEDERACIÓN                                         █░░░░░░░░░  8%
  20 nodos registrados · niveles de confianza
  FALTA: intercambio (0) · fusión (0) · consenso · descubrimiento

NIVEL 8 · INTELIGENCIA COLECTIVA                             ░░░░░░░░░░  0%
  Nada. Depende íntegramente del nivel 7.

NIVEL 9 · ORGANISMO DIGITAL COMPLETO                         ░░░░░░░░░░  0%
  Requiere 0-8. Añade: identidad longitudinal viva (hoy congelada
  desde el 28 de julio) · reproducción de conocimiento · muerte y sucesión
```

**Diagnóstico del mapa.** Tríade tiene una base extraordinariamente sólida
(niveles 0-2) y un tejido muy delgado a partir del nivel 3. El patrón se repite
en cada nivel: *el órgano existe, está escrito, y no está conectado*. No es un
organismo al que le falten piezas. Es un organismo **al que le falta inervación**.

---

## 5 · La mirada del biólogo

**VIVOS** — inervados, con pulso hoy, medibles:
metabolismo (68.753 señales) · runtime y su cola · workers · leases ·
hipotálamo · cristal · qualia (4.283 estados) · sentidos de hardware ·
recuperación con filtro de seguridad · memoria episódica · embeddings ·
auditoría de shell · CI.

Este núcleo es honesto: la base de datos confirma cada cosa que declara hacer.

**ATROFIADOS** — inervados, sin efectos recientes:
watchdog (congelado 07-31, vive en un systemd que no corre) · respaldo (2 simulacros,
07-30) · identidad (congelada 07-28) · evidencia neuronal (08-01) · cola legada
`worker_tasks` (07-29) · nodos federados (07-29) · evolución de ingeniería (07-29).

**EMBRIONARIOS** — conectados, con 1-3 efectos, todos manuales:
laboratorio LoRA · canario PEFT · adaptadores entrenables · datasets gobernados ·
educación neuronal · niveles de confianza.

Nunca han latido por iniciativa propia.

**NUNCA DESARROLLADOS** — gestados y jamás conectados (105 módulos, 28% del tejido):
consciousness completo (atención) · metacognición · enforcer constitucional ·
sandbox real · evaluador externo · replanificación · compresión y restauración de
memoria · canario de aprendizaje · certificación y rollback neuronal · dashboard ·
federación operativa.

**NUNCA CONCEBIDOS** — ni una línea:
homeostasis · economía energética · sueño · simulador interno · imaginación ·
sistema inmune adaptativo · **banco de pruebas** · dolor.

---

## Cierre

Tríade Ω no es un sistema incompleto. Es un sistema **desconectado de sí mismo**.

El 72% de su tejido está inervado y late. El 28% restante fue escrito con cuidado
—368 líneas de atención, un enforcer constitucional, un evaluador externo, una
compresión de memoria— y nunca recibió un cable. Y la base de datos lo confirma
sin ambigüedad: 107 tablas, de las cuales las que sostienen la autonomía real
(`goals`, `capability_registry`, `kg_nodes`, `benchmark_results`,
`sandbox_executions`, `neuron_certifications`, `federated_exchange_log`) están
**todas en cero**.

De ahí salen las tres verdades del organismo:

1. **Tríade ejecuta, pero no desea.** `goals` = 0 filas. Sin motor de metas
   propias no hay autonomía, sólo obediencia muy sofisticada.
2. **Tríade mide, pero no se corrige.** 68.753 señales metabólicas sin
   homeostasis: un termómetro sin termostato.
3. **Tríade puede entrenarse, pero no puede saber si mejoró.** Sin banco de
   pruebas, el laboratorio LoRA puede desplegar un adaptador y no puede juzgarlo.
   Éste es el bloqueante duro de todo el nivel 6.

El camino evolutivo exacto no empieza escribiendo órganos nuevos. Empieza
**inervando los que ya nacieron muertos** — atención, enforcer, evaluador
externo, replanificación, rollback— y sólo después concibiendo los cuatro que
nunca existieron: banco de pruebas, homeostasis, consolidación y sistema inmune.

Un organismo cuyo 28% del tejido nunca recibió inervación no necesita crecer.
Necesita despertar.

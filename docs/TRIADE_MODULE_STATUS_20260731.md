# Estado real de Tríade por módulos · 2026-07-31

Actualiza el análisis de lo que falta, tras el arreglo de preservación
neuronal. Todo lo marcado **[medido]** viene de la base real
(`triade/memory/triade.db`, 105 tablas) o de una ejecución observada hoy. Lo
marcado **[no verificado]** no se comprobó en este encargo y no debe leerse
como verde ni como rojo.

## Lo que cambió hoy

El registro neuronal dejaba de ser fiable en cada reinicio. Eso invalidaba
cualquier medición de "competencia neuronal" anterior: no se estaba midiendo
qué aprendían las neuronas, sino qué sobrevivía al último arranque.

## Hechos medidos hoy

| hecho | valor | de dónde sale |
|---|---|---|
| Neuronas registradas | 21 | `neurons` |
| Fundacionales reescritas en cada arranque | 10 de 10, `updated_at` = hora del reinicio | `neurons`, arranque 22:30:40 |
| Especializadas con triggers borrados | 2 de 2, `triggers=[]` | `neurons`, arranque 22:22:02 |
| `learning_queue` | **628 candidatos, todos en `internally_checked`** | `learning_queue` |
| `learning_evidence` | **1 fila**, en estado `pending`, con `evidence_refs=[]` | `learning_evidence` |
| `improvement_proposals` | **la tabla no existe en producción** | `sqlite_master` |
| `verification_reports` | 196 | `verification_reports` |
| Documentos semánticos | 156, todos `candidate` | `semantic_documents` |
| Embeddings | 156 `stored`, **0 pendientes** | `semantic_embeddings` |
| Integridad de la base | `integrity_check = ok` | copia de producción |
| Claves ajenas | `PRAGMA foreign_keys = 0`, 3435 violaciones preexistentes | copia de producción |

Dos correcciones a supuestos previos:

- **Los embeddings no son un cuello de botella.** 156 de 156 documentos tienen
  embedding; no hay backlog. Lo pendiente no es `embed_pending()`, es que
  ningún documento pasa de `candidate`.
- **A `improvement_proposals` no le falta combustible: le falta el depósito.**
  `triade/self_improvement/store.py:44` crea la tabla con `CREATE TABLE IF NOT
  EXISTS`, así que su ausencia significa que el store **nunca se ha
  instanciado en producción**. El consumidor no está esperando propuestas:
  no está corriendo.

## Estado por módulo

| módulo | estado | caller de producción | evidencia | qué falta | prioridad |
|---|---|---|---|---|---|
| Neuron Registry | **arreglado hoy** | `single_port_app:97`, `model_acquisition` | 23 tests + copia real | recuperar los triggers ya perdidos | 1 |
| Neuron Creator | vivo | `runner`, `life_pulse`, `self_reflection` | 21 neuronas creadas | — | — |
| Neuron Trainer | vivo | `neuron_registry.store_training` | [no verificado] cobertura real | medir uso real | 3 |
| Fundacionales | **arreglado hoy** | arranque | 10 neuronas `stable` | ninguna aprende aún | 1 |
| Especializadas / Model Acquisition | **arreglado hoy** | `start_model_acquisition_background` | 2 neuronas | reaprender triggers | 1 |
| Trigger Learning | vivo, **por fin persistente** | `NeuronTriggerLearner` | 7 y 8 triggers en copia real | conectarlo al ciclo 24/7 | 2 |
| Learning Queue | **atascado** | activo | 628 en un solo estado | productor de evidencia | 2 |
| Evidence Bridge / Measurement | parcial | — | 1 `learning_evidence` `pending` | cerrar el ciclo hasta `RegressionGate` | 2 |
| Self Improvement | **no arrancado en producción** | ninguno observado | tabla inexistente | instanciar el store y su productor | 3 |
| RegressionGate | implementado | `gate.py` | tests pasan | sin tráfico real | 3 |
| Canary | implementado | — | sin `canary_runs` en la base | causalidad: falta `routing_decision_id` y digests | 5 |
| Workers / Concurrencia / Leases | vivo | `worker_autostart` | 1802 completadas, 13 fallidas, 2887 saltadas, 21 bloqueadas | 24 h estables antes de activar concurrencia global | 4 |
| Scheduler / Watchdog | vivo | arranque | 50 ciclos/24 h | — | — |
| Cabina Viva / API | **vivo y público** | uvicorn :8010 | HTTP 200 público y local | — | — |
| Ollama | **vivo** | `ollama serve` | 6 modelos, latencia 1.5 ms | — | — |
| Semantic Store / Embeddings | vivo y al día | activo | 156/156 | ningún documento se consolida | 3 |
| Model Router / Acquisition | vivo | arranque | 4 modelos seleccionados por rol | `status='discovered'` fijo en UPSERT (P1) | 2 |
| Observabilidad | vivo | heartbeat | 40+ campos | `latest_error: unknown_handler_status` recurrente | 3 |
| SQLite | ok con reservas | — | `integrity_check ok` | 3435 violaciones de FK, FK desactivadas | 3 |
| CI | [no verificado] hoy | GitHub Actions | — | jobs serial/concurrente separados | 4 |
| Cristal, Qualia, Hipotálamo, Bodega, Safety, Verifier, Contributions, GovernedPlanDispatcher, Federación, LoRA, UI, Deployment | **[no verificado]** en este encargo | — | — | no se auditaron; no cambian de estado | — |

## Roadmap

| # | trabajo | depende de | prueba de aceptación | cierre |
|---|---|---|---|---|
| 1 | Preservación neuronal | — | 23 tests + copia real sin diferencias tras 2 arranques | **hecho**, salvo recuperar lo perdido |
| 2 | Mismo patrón en Model Registry y Federación | 1 | `status` no vuelve a `discovered`/`active` al re-registrar | pendiente |
| 3 | Productor de evidencia del aprendizaje | 1 | de 628 candidatos, ≥1 llega a `learning_evidence` completa y pasa `RegressionGate` sin bajar el gate | pendiente |
| 4 | Instanciar el store de automejora | 3 | la tabla existe y se puebla sola | pendiente |
| 5 | CI serial y concurrente reproducible | — | verde con `TRIADE_WORKER_CONCURRENCY` 0 y 1, repetido | pendiente |
| 6 | Canary causal | 4 | `routing_decision_id`, `actual_candidate_used`, digests; hasta entonces `causal_attribution="temporal_only"` | pendiente |
| 7 | Concurrencia global | 5 | 24 h sin `database is locked`, sin tareas huérfanas, cierre limpio | **no declarar listo** |
| 8–13 | Routing neuronal real, Cristal en workers, dispatcher productivo, gate humano visual, LoRA, Core generacional, federación | anteriores | — | pendiente |

## Lo que no se puede afirmar todavía

- Que el aprendizaje **se consolida**: 628 candidatos y 1 evidencia incompleta.
- Que el canary es **causal**: faltan los identificadores de decisión.
- Que la concurrencia está **lista**: no hay 24 h de evidencia.
- Que LoRA sirve tráfico: no se tocó.
- Que las neuronas **han aprendido**: hoy sólo se ha garantizado que, cuando
  aprendan, no lo pierdan al reiniciar.

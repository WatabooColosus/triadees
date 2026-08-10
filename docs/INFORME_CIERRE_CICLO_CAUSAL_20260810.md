# Cierre del ciclo causal y reducción de deuda · 2026-08-10

Trabajo sobre `main` en `61d65f3` (merge del PR #102), verificado contra
`origin/main` con árbol limpio antes de empezar. Todas las cifras de este
informe están medidas en esta sesión sobre la base viva; ninguna se reutiliza
del PR #102.

## 1. El gate que impedía consolidar

`/api/internal-graphs/debt` reprodujo exactamente el estado de #102 —46 items,
31 deuda real— y el candidato `exp-519aacaca33d4a09` seguía en
`evidence_verified` con 3 usos causales y score medio 1.0, esperando
consolidación.

La causa no era el presupuesto agotado. `ResourceLedger.policy()` metía en un
mismo `max()` dos cosas de naturaleza distinta:

- **recursos físicos compartidos** (CPU, GPU, red, disco), cuya escasez es real
  y justifica degradar el organismo entero;
- **cupos por clase** (`research_tasks_daily`, `deep_evaluations_daily`,
  `model_installs_daily`), que no son escasez sino un permiso contado.

Mezclarlos producía tres patologías, las tres medidas:

| patología | evidencia |
|---|---|
| **auto-inanición** | al 70 % de su propia línea la clase se prohibía a sí misma: `deep_evaluations_daily=12` rendía 9. La base tiene **tres días seguidos** —2026-08-08, 09 y 10— con exactamente 9 `stable_consolidation_review`, todas entre 00:00 y 00:41 UTC y ninguna después |
| **contaminación cruzada** | 32 investigaciones de 40 (0.80) apagaban la evaluación profunda, que iba por 0.75 y tenía sitio |
| **suicidio por instalación** | `model_installs_daily=1`: gastar el único permiso presupuestado ponía la razón en 1.0 y el organismo entero en `observe_only` hasta medianoche |

El presupuesto **sí se renueva** correctamente: `daily_usage()` particiona por
`recorded_day`, así que el corte es la medianoche UTC y no lo ejecuta ningún
componente. Lo que fallaba era el gasto, no la renovación.

**Arreglo:** la escalera de degradación (0.70/0.85/0.95/1.0) se calcula sólo
sobre recursos físicos; cada cupo limita únicamente su propia clase y se agota
en su límite, no antes. **Ningún umbral ni límite declarado se ha modificado.**
`policy()` expone además `quotas` y `exhausted_quotas`, porque «clase parada» y
«cupo agotado» son hechos distintos que la observabilidad no podía separar.

De paso: `runtime_budget` llevaba declarado en `triade.yml` sin que lo leyera
nadie —los tres constructores usaban `DEFAULT_BUDGET`—. Hoy las cifras coinciden
y el error era invisible; ahora el fichero es la fuente.

**Resultado medido:** hoy el cupo de evaluación profunda llegó a **12/12 por
primera vez**. El límite declarado dejó de ser inalcanzable.

## 2. La cadena causal, con identificadores reales

A las **03:31:57 UTC** el worker consolidó sin intervención humana:

```
REQUEST/RUN        run-20260810-012416-813e7682
CANDIDATO          exp-519aacaca33d4a09  (source_type=experience, domain=conversation)
EVIDENCIA          ev-b4a27ad842bb4328   baseline 0.0 → candidate 1.0, delta 1.0, decision=improved
USO CAUSAL         3 usos, avg_outcome_score 1.0
REVISIÓN           task-0e1c1623f1c44bfa8e  (stable_consolidation_review)
APROBADOR          worker-stable-review:worker-2026-08-10T033051.859401Z0000-34a934f0
MEMORIA SEMÁNTICA  sem-f75a060daef94b98   status=stable
RECUPERACIÓN       gobernanza: decision=allowed, allowed_to_influence=true, canal=keyword
EFECTO             run-20260810-035334-c125b4d6 y siguientes responden el dato exacto
```

Nota de honestidad sobre el campo `auto_consolidated: false`: significa «no vía
el sistema de confianza», porque el worker pasa un aprobador explícito. La
consolidación **sí** fue autónoma; el único `consolidated` anterior (2026-08-09)
llevaba `approved_by: certificacion-fase8:forzado-por-operador`, que no lo era.

## 3. Repetibilidad: tres aprendizajes independientes

Sembrados por conversación real y llevados por la cadena sin intervención en
ningún paso salvo preguntar:

| candidato | hecho | evidencia | usos | estado |
|---|---|---|---|---|
| `exp-6afda5f39b26430b` | `ENTORNO_LIMA_4462` | `improved` 0.0→1.0 | 3 | `evidence_verified` |
| `exp-c50522e1125e4723` | `VENTANA_JUEVES_0300` | `improved` 0.0→1.0 | 4 | `evidence_verified` |
| `exp-de6f666aca5a4aaa` | `INFORME_CETRO_9051` | `improved` 0.0→1.0 | 3 | `evidence_verified` |

Los tres responden correctamente en conversaciones nuevas y encabezan la cola de
`list_consolidatable`. Consolidarán en la renovación de cupo de las 00:00 UTC:
el cupo del día se agotó **antes** de que acumularan sus usos causales. **No se
ha forzado la consolidación**, que es lo que pedía el encargo.

Métricas del ciclo: `candidates_created` 25, `education_passed` 25 (todos
alcanzaron `internally_checked`), `evidence` +20, `improved` 3, `not_measurable`
3, `consolidated` 1, `causal_uses` 13 sobre 4 candidatos, `rejected` por gate
legítimo en cada revisión (`No existe evidencia Measurement Core`,
`decision=neutral`, `decision=not_measurable`).

Los tres candidatos `learn-*` hermanos —la transcripción post-run del mismo
intercambio— salieron `not_measurable`, que es correcto: una transcripción del
modelo no es fuente factual, y el extractor de conversación produjo aparte el
candidato tipado que sí lo es.

## 4. La similitud vectorial estaba declarada y muerta

`semantic_recall` reporta `mode: vector_similarity`. Los 351 documentos de la
base tenían vector de `triade-local-hash:64` mientras la consulta se embebe con
`nomic-embed-text` a 768 dimensiones: **ninguno podía casar nunca**. Cada run
devolvía `status: ok` con `matches_count: 0`, `skipped_model: 350` y
`retrieved_vector_matches: 0`. Lo que salvaba la recuperación era el canal de
palabras clave, que tapaba el agujero lo bastante bien como para que el estado
pareciera sano.

La causa no es un error: el único llamador productivo pasa
`auto_ollama_embed=False` porque embeber dentro de una conversación la frena.
Faltaba el otro extremo. El motor que embebe de verdad ya existía y no lo
disparaba nadie: `_semantic_memory_governance` se llamaba «gobernanza» y sólo
llamaba a `doctor()`.

Ahora drena fuera de la ruta caliente, de diez en diez. Sin borrar el vector
viejo: `store_embedding` es único por `(document_id, embedding_model)`, así que
el hash queda inerte y el bueno se añade. **171 vectores reales** al cierre de
esta sesión, subiendo.

## 5. Contradicción: el gate que faltaba

`consolidate()` comprobaba estado, procedencia, riesgo, usos, score, evidencia
de Measurement Core, rollback obligatorio, constitución, aislamiento
embedding↔evaluación y consejo de verificación. No comprobaba si el candidato
afirma lo contrario de lo ya consolidado. Dos hechos incompatibles en `stable`
los devuelve la misma consulta y lo que llega al modelo deja de ser memoria.

`find_contradiction` compara sujeto y dato reutilizando `extract_target`, el
mismo extractor con el que `knowledge_probe` decide si un candidato es medible.
Bloquea, no resuelve: elegir cuál de las dos afirmaciones sobrevive no es
decisión de un worker. Verificado sobre la base viva que no bloquea nada de lo
ya consolidado.

**Batería adversarial (13 pruebas).** Dos de las cinco vías resultaron mejor
defendidas de lo supuesto y los tests fijan la conducta real, no la esperada:

- el duplicado no llega a nacer, `ingest` funde por contenido;
- sin evidencia medida no se puede ni acumular uso causal, porque
  `mark_used_in_run` llama a `require_improvement()` en cuanto los umbrales se
  alcanzarían.

Se mantiene el bloqueo de `unverified_model_transcript` de #101, con prueba de
que una preferencia tipada por el usuario sí pasa.

## 6. Deuda real: 31 → 21

Diez de las treinta y una eran tablas cuya retirada **ya estaba decidida,
escrita y probada** en `034_retire_orphan_schema.sql` y
`035_retire_neuron_certifications.sql`, sin haberse ejecutado nunca contra
ninguna base. La razón: Tríade no tiene aplicador central de migraciones —cada
módulo corre la suya cuando la necesita— y una retirada no la necesita nadie.

`scripts/apply_schema_retirements.py` es esa ruta: dry-run por defecto, se niega
a borrar una tabla con filas y lo reporta, copia de seguridad y manifiesto con
el `CREATE TABLE` de cada tabla, y `--rollback MANIFIESTO` para deshacer.
Aplicado con autorización explícita del operador:

```
backup:   artifacts/migrations/pre-retirement-20260810T040620Z.db
manifest: artifacts/migrations/retirement-20260810T040622Z.json
retiradas: benchmark_results, benchmark_tasks, federated_merge_log,
           federated_merge_nodes, meta_model_candidates, meta_model_decisions,
           meta_model_evaluations, metabolic_config, user_sessions,
           neuron_certifications
```

Verificado tras aplicar, con el organismo vivo: ninguna volvió a crearse,
`integrity_check ok`, `foreign_key_check` 0, `/health/deep healthy`.

`036_retire_goals.sql` queda **sin aplicar** por decisión del operador: exige
rebasar el ancla de identidad con `migrate_anchor()` y sin eso el runtime
arranca en `degraded_safe_identity_mismatch`.

Dato que sólo apareció por volver a medir: escribir el aplicador subió la deuda
de 31 a 32. Mi test nombraba literalmente las tablas retiradas —lo que el
detector de alias lee, con razón, como «lector apuntando al gemelo muerto»— y mi
script no era reversible de verdad, así que el detector de entrypoints tampoco
lo reconocía. Corregidas ambas cosas en su origen, no en el detector.

## 7. Dead letters: 181 históricas, 0 vigentes

`scripts/triage_dead_letters.py` clasifica por causa raíz y por si reintentar
tendría valor. **Ninguna lo tiene:**

| clasificación | n | qué es |
|---|---|---|
| `superseded_periodic` | 155 | tarea periódica cuyo trabajo ya hizo una instancia posterior que sí completó |
| `uncertain_quarantined` | 15 | el runtime no pudo demostrar que se completara y la cerró a propósito |
| `handler_unverifiable` | 5 | el handler afirmó un efecto sin recibo verificable |
| `environment` | 6 | faltaba clave de backup o binario en PATH |
| **`active_bug`** | **0** | — |

Causas: `lease_expired` 142, `timeout` 9, `state_race` 4. Última muerte:
**2026-08-09T21:17:32**, antes de los arreglos finales de #102. Nada ha muerto
desde entonces ni durante el soak.

El orden de clasificación importó: mirar la recencia primero marcaba 92 muertes
como bug vigente sólo porque la hemorragia se cerró siete horas antes y la
ventana era de veinticuatro. «Murió hace poco» y «la causa sigue mordiendo» son
cosas distintas.

## 8. Tabla comparativa

Cifras medidas. «Antes» = inicio de sesión sobre `61d65f3`; «después» = cierre.

| | ANTES | DESPUÉS |
|---|---|---|
| deuda real | 31 | **21** |
| deuda total (items) | 46 | **37** |
| FK violations | 0 | 0 |
| FK violations nuevas | 0 | 0 |
| dead letters | 181 | 181 |
| dead letters nuevas | 0 | **0** |
| workers atascados | 0 | 0 |
| cupo de evaluación profunda gastable | 9 de 12 | **12 de 12** |
| candidatos en `learning_queue` | 851 | 876 |
| evidencias medidas | 327 | 347 |
| `evidence_verified` | 15 | 17 |
| consolidados | 1 (forzado por operador) | **2 (1 autónomo)** |
| documentos semánticos `stable` | 1 | **2** |
| vectores que la búsqueda puede encontrar | **0** de 351 | **171** y subiendo |
| usos causales confirmados | 3 (1 candidato) | **13 (4 candidatos)** |
| aprendizajes independientes medidos `improved` | 1 | **4** |
| gates de consolidación | 10 | **11** (contradicción) |
| errores de build de frontend | 0 | 0 |
| errores de `tsc --noEmit` | 6 | **0** |

## 9. Matriz por subsistema

| subsistema | veredicto | evidencia |
|---|---|---|
| **Runtime** | CERTIFIED | 62 min de soak sin fallos; `/health/deep healthy`; `integrity ok`; FK 0; 515 recuperaciones históricas y 0 nuevas |
| **Workers** | CERTIFIED | 16.578 tareas, 0 `leased` colgadas, 0 dead letters nuevas, 31.216 transiciones registradas |
| **Scheduler** | FUNCTIONAL | 17.403 entradas de historia, 19 métricas por tipo; el cupo por clase ya no se auto-bloquea |
| **Memory** | FUNCTIONAL | 369 documentos, 2 `stable`, recuperación gobernada con veredicto por documento. Vectorial en reparación activa: 171 de 369 |
| **Learning** | CERTIFIED | ciclo completo con identificadores reales; 4 aprendizajes medidos `improved`; 13 usos causales; 11 gates con batería adversarial |
| **Goals** | PARTIAL | `planning_graph` 30 filas y `goal_events` 8 vivos; `goal_dependencies` y `goal_learning_observations` en cero: escritor alcanzable, sin disparo natural |
| **Improvement** | BLOCKED (por diseño) | `improvement_history` 5, `failure_lessons` 5, `signals` 1; propuestas y canarios en cero tras aprobación humana, clasificado HUMAN_GATED con contrato verificado |
| **Neurons** | FUNCTIONAL | 28 neuronas, 26 misiones, 679 ciclos/evidencias/scores, 60 sesiones de educación, 16 entrenamientos. `neuron_candidates`/`specifications` en cero |
| **Federation** | CAPABILITY READY / EXTERNAL DEPENDENCY | 20 nodos registrados, transporte probado; `federated_exchange_log` en cero porque no hay segundo nodo. Las tablas de merge huérfanas ya retiradas |
| **Safety** | CERTIFIED | 509 informes de verificación, 319 de regresión, 288 auditorías de shell, consejo convocado en la consolidación real (`council_decisions` 1→2) |
| **Observability** | FUNCTIONAL | contrato de deuda medido y reproducible; triaje de dead letters nuevo; `quotas`/`exhausted_quotas` expuestos |
| **Frontend** | PARTIAL | `npm ci`, `npm run build`, `npm audit` (0 vulnerabilidades) y `tsc --noEmit` verdes. La consola operacional no se ha abordado; ver §10 |

## 10. Lo que queda abierto

Se dice explícitamente porque no está hecho:

1. **Consola frontend (§16–23 del encargo).** No abordada: ni el panel de
   aprendizaje, ni la distinción `ALIVE/PROGRESSING/LEARNING/IMPROVING`, ni la
   timeline forense, ni la búsqueda global, ni la deuda navegable, ni el drill-down
   del SYSTEM 3D, ni SSE. Sí se cerró la divergencia de contrato que se encontró
   de camino: `DashboardData` declaraba 11 de las 21 claves que el backend envía
   y el componente usaba cinco de las que faltaban. `tsc --noEmit` queda limpio,
   aunque conviene saber que **CI no lo ejecuta**, así que ese tipo de
   divergencia no aparece como check rojo.
2. **Consolidación de los tres aprendizajes nuevos**, a la espera de la
   renovación de cupo de las 00:00 UTC. Deliberadamente no forzada.
3. **`goals`**, pendiente de la decisión gobernada sobre el ancla de identidad.
4. **`goal_dependencies`, `goal_learning_observations`, `kg_*`,
   `relational_modulation_*`, `neuron_candidates`, `sandbox_executions` y
   compañía**: 20 de las 21 deudas restantes son tablas con escritor alcanzable
   y sin disparo natural. Auditadas y clasificadas, no reparadas.
5. **Crecimiento de RSS** durante el soak: 250 → ~390 MB en la primera media
   hora, coincidiendo con el drenaje de embeddings. No se ha caracterizado si se
   estabiliza.

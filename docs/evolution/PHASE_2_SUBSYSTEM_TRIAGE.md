<!-- HISTORICO -->
# Fase 2 — Triaje individual de subsistemas

## SHA base, rama y objetivo

- SHA base: `9a035cc6837aa8a1518b7e145ac301970a627f5e`.
- Rama: `main`.
- Objetivo: revisar individualmente las 72 observaciones `incomplete_subsystem` sin reducir ni ocultar deuda.

## Estado inicial y método

La fuente canónica es `artifacts/debt/debt-triage-20260803.json`: 72 observaciones y 49 subsistemas únicos. 22 subsistemas aparecen en dos o tres categorías; se conservan todos los IDs y cada duplicación referencia los otros hallazgos.

El generador inspecciona código, grafo de tablas, alcanzabilidad desde entrypoints, filas runtime, pruebas y última actividad Git. La automatización valida evidencia y completitud; no inventa activación.

## Diferencia de estados

- **Código existente:** ficheros o tablas identificados en repositorio/grafo.
- **Código alcanzable:** alguna referencia deriva de un entrypoint vivo.
- **Código probado:** una prueba nombra el subsistema; no implica E2E.
- **Código ejecutado:** existe ejecución observada, no sólo declaración.
- **Runtime observado:** filas y actividad vienen del artefacto vivo de origen.
- **Capacidad demostrada:** exige productor, consumidor, entrypoint, E2E y observabilidad; ninguno de estos 72 cumple todo el gate.

## Hallazgos y causas

- La deuda mezcla tablas vacías, task types nunca ejecutados, telemetría sin lector, módulos huérfanos y experimentos.
- Una tabla con filas no demuestra utilidad si nadie las consume; una tabla vacía no se completa creando filas artificiales.
- Los módulos experimentales permanecen etiquetados como tales.
- No se modifica identidad, secretos, permisos ni fronteras de seguridad.

## Decisiones

| Decisión | Cantidad |
|---|---:|
| `activate_now` | 0 |
| `complete_later` | 42 |
| `merge_with_existing` | 9 |
| `experimental_keep` | 17 |
| `legacy_archive` | 1 |
| `remove_from_productive_graph` | 3 |

No hay `activate_now`: ante ausencia de E2E u observabilidad la decisión obligatoria es no demostrado.

## Revisión 72/72

| ID | Grupo | Subsistema | Owner | Alcanzable | Filas | Decisión | Prioridad | Razón |
|---|---|---|---|---:|---:|---|---|---|
| D002 | A | benchmark_tasks | evaluation | no | 0 | `merge_with_existing` | P2 | Está vacío y desconectado mientras autonomous_tasks ya ofrece cola y ciclo de vida. |
| D004 | A | neuron_education_applications | learning | sí | 0 | `complete_later` | P1 | Tiene lectores y escritores reales pero cero uso runtime; no hay prueba de aplicación end-to-end. |
| D007 | A | capability_history | capabilities | sí | 0 | `complete_later` | P2 | La ruta existe pero nunca produjo filas observadas. |
| D008 | A | capability_registry | capabilities | sí | 0 | `complete_later` | P1 | Lectores y escritor existen, pero el registro vivo permanece vacío y no está validado E2E. |
| D012 | A | governed_peft_active_slot | models | sí | 0 | `complete_later` | P2 | El slot no registra actividad y no existe promoción demostrada en runtime productivo. |
| D013 | A | kg_contradictions | knowledge | sí | 0 | `experimental_keep` | P3 | La arquitectura está implementada pero no tiene hechos runtime ni consumidor productivo demostrado. |
| D014 | A | kg_edges | knowledge | sí | 0 | `experimental_keep` | P3 | La tabla está vacía y el grafo semántico no está demostrado productivamente. |
| D015 | A | kg_nodes | knowledge | sí | 0 | `experimental_keep` | P3 | Tiene código estructural sin datos ni uso productivo observado. |
| D016 | A | neuron_certifications | verification | no | 0 | `remove_from_productive_graph` | P2 | Retirada el 2026-08-08. El `complete_later` anterior daba por construir un productor que ya existe con otra forma: `stable_neuron_audit` decide sobre evidencia medida —activaciones, diagnósticos, planes de prueba— y lo consumen cinco sitios vivos. El manifiesto firmado a mano nunca tuvo escritor, y su único lector era el instrumento de la fase 12, `completed` desde el 2026-07-29. |
| D017 | A | neuron_education_applications | learning | sí | 0 | `complete_later` | P1 | Tiene lectores y escritores reales pero cero uso runtime; no hay prueba de aplicación end-to-end. |
| D019 | A | regression_quarantine | regression | sí | 0 | `complete_later` | P1 | El gate existe, pero la cuarentena persistida no se ha ejercitado en runtime. |
| D023 | A | semantic_governance_events | memory | sí | 0 | `complete_later` | P1 | Lectores y escritores existen sin eventos runtime observados. |
| D024 | A | semantic_memory | memory | sí | 0 | `complete_later` | P1 | Diez lectores y tres escritores no han producido filas en la base observada; no equivale a aprendizaje. |
| D025 | A | stable_capability_state | capabilities | sí | 0 | `complete_later` | P1 | La estructura existe sin estado runtime ni reutilización productiva demostrada. |
| D050 | A | triade/capabilities/matrix.py | capabilities | no | UNKNOWN | `remove_from_productive_graph` | P2 | Retirada el 2026-08-08. El `merge_with_existing` anterior daba por supuesto que quedaba lógica no duplicada que extraer; medida sobre el registro ya lleno, no queda ninguna: los ciclos y las críticas sin rollback los rechaza `register()` al escribir, `quarantined` no lo asigna nadie, el baseline lo juzga y lo aplica `MandatoryRollbackEnforcer` y los recuentos los publica `CapabilityObservability`. |
| D054 | A | capability_history | capabilities | sí | 0 | `complete_later` | P2 | La ruta existe pero nunca produjo filas observadas. |
| D055 | A | capability_registry | capabilities | sí | 0 | `complete_later` | P1 | Lectores y escritor existen, pero el registro vivo permanece vacío y no está validado E2E. |
| D059 | A | governed_peft_active_slot | models | sí | 0 | `complete_later` | P2 | El slot no registra actividad y no existe promoción demostrada en runtime productivo. |
| D060 | A | kg_contradictions | knowledge | sí | 0 | `experimental_keep` | P3 | La arquitectura está implementada pero no tiene hechos runtime ni consumidor productivo demostrado. |
| D061 | A | kg_edges | knowledge | sí | 0 | `experimental_keep` | P3 | La tabla está vacía y el grafo semántico no está demostrado productivamente. |
| D062 | A | kg_nodes | knowledge | sí | 0 | `experimental_keep` | P3 | Tiene código estructural sin datos ni uso productivo observado. |
| D063 | A | neuron_education_applications | learning | sí | 0 | `complete_later` | P1 | Tiene lectores y escritores reales pero cero uso runtime; no hay prueba de aplicación end-to-end. |
| D065 | A | regression_quarantine | regression | sí | 0 | `complete_later` | P1 | El gate existe, pero la cuarentena persistida no se ha ejercitado en runtime. |
| D070 | A | semantic_governance_events | memory | sí | 0 | `complete_later` | P1 | Lectores y escritores existen sin eventos runtime observados. |
| D071 | A | semantic_memory | memory | sí | 0 | `complete_later` | P1 | Diez lectores y tres escritores no han producido filas en la base observada; no equivale a aprendizaje. |
| D072 | A | stable_capability_state | capabilities | sí | 0 | `complete_later` | P1 | La estructura existe sin estado runtime ni reutilización productiva demostrada. |
| D073 | A | benchmark_results | evaluation | no | 0 | `legacy_archive` | P3 | Tabla viva sin productor ni consumidor; los artefactos versionados son hoy la fuente demostrada. |
| D074 | A | benchmark_tasks | evaluation | no | 0 | `merge_with_existing` | P2 | Está vacío y desconectado mientras autonomous_tasks ya ofrece cola y ciclo de vida. |
| D086 | A | neuron_certification_transitions | verification | no | 13 | `complete_later` | P2 | Existen 13 transiciones sin lector, así que no gobiernan promoción ni revisión. |
| D093 | A | stable_consolidation_review | learning | sí | UNKNOWN | `complete_later` | P1 | Task type nunca ejecutado pese a que consolidación requiere consumidor y auditoría. |
| D001 | B | unhealthy | workers | no | UNKNOWN | `remove_from_productive_graph` | P1 | El estado es inalcanzable y no tiene productor; presentarlo como vivo falsea la supervisión. Medido el 2026-08-08: el problema no es el valor sino su casa. `worker_supervisor` está `disconnected` en el grafo de workers con `live_importers: []`, y sus cinco tablas —incluida `worker_health_snapshots`— no existen en la base viva. La comparación no devuelve cero: no se evalúa nunca. |
| D005 | B | runtime_queue_compatibility_events | runtime | no | 0 | `merge_with_existing` | P2 | Escribe una tabla vacía que se solapa con runtime_queue_compatibility, ya activa. |
| D010 | B | goal_dependencies | goals | sí | 0 | `complete_later` | P1 | Escritor y lector no han producido actividad; depende de cerrar Goals E2E. |
| D011 | B | goals | goals | sí | 0 | `complete_later` | P1 | El circuito existe pero tiene cero filas y carece de validación end-to-end. |
| D018 | B | orchestrator_locks | runtime | sí | 0 | `complete_later` | P1 | Hay lectores/escritores pero no actividad observada ni prueba de exclusión global. |
| D052 | B | triade/core/plan_step.py | goals | no | UNKNOWN | `merge_with_existing` | P2 | Módulo huérfano que se solapa con contratos de planning ya usados. |
| D057 | B | goal_dependencies | goals | sí | 0 | `complete_later` | P1 | Escritor y lector no han producido actividad; depende de cerrar Goals E2E. |
| D058 | B | goals | goals | sí | 0 | `complete_later` | P1 | El circuito existe pero tiene cero filas y carece de validación end-to-end. |
| D064 | B | orchestrator_locks | runtime | sí | 0 | `complete_later` | P1 | Hay lectores/escritores pero no actividad observada ni prueba de exclusión global. |
| D068 | B | runtime_queue_compatibility_events | runtime | no | 0 | `merge_with_existing` | P2 | Escribe una tabla vacía que se solapa con runtime_queue_compatibility, ya activa. |
| D087 | B | bodega_global_review | workers | sí | UNKNOWN | `complete_later` | P2 | Task type declarado pero nunca ejecutado; no hay evidencia de efecto ni terminación. |
| D088 | B | federation_inbox_review | federation | sí | UNKNOWN | `complete_later` | P2 | Task type sin ejecución observada; la entrada federada añade riesgo de seguridad. |
| D089 | B | goal_install | goals | sí | UNKNOWN | `complete_later` | P1 | Nunca ejecutada y puede instalar dependencias, operación que requiere aprobación explícita. |
| D090 | B | goal_lora_train | goals | sí | UNKNOWN | `complete_later` | P2 | Nunca ejecutada; coste GPU y promoción requieren contratos de workers y modelos. |
| D095 | B | plan: 51 filas, ninguna en 24 h | goals | no | UNKNOWN | `complete_later` | P1 | Hay historia, pero ninguna actividad reciente; no demuestra un circuito actual vivo. |
| D006 | C | auto_identity | identity | sí | 0 | `complete_later` | P3 | Hay código lector/escritor pero cero evidencia runtime; identidad es frontera protegida. |
| D022 | C | sandbox_executions | sandbox | sí | 0 | `complete_later` | P1 | El almacén existe pero no contiene ejecuciones; el sandbox fuerte es trabajo de Fase 6. |
| D053 | C | auto_identity | identity | sí | 0 | `complete_later` | P3 | Hay código lector/escritor pero cero evidencia runtime; identidad es frontera protegida. |
| D069 | C | sandbox_executions | sandbox | sí | 0 | `complete_later` | P1 | El almacén existe pero no contiene ejecuciones; el sandbox fuerte es trabajo de Fase 6. |
| D081 | C | user_sessions | security | no | 0 | `merge_with_existing` | P2 | Tabla desconectada que puede solaparse con el mecanismo actual de autenticación. |
| D094 | C | write_governed_text_artifact | sandbox | sí | UNKNOWN | `complete_later` | P1 | Operación de filesystem nunca ejecutada; requiere rutas permitidas e idempotencia. |
| D003 | D | federated_merge_nodes | federation | no | 0 | `merge_with_existing` | P2 | Duplica federated_nodes, que sí contiene actividad runtime. |
| D009 | D | federated_exchange_log | federation | sí | 0 | `complete_later` | P2 | Tiene circuito estructural pero no actividad runtime observada. |
| D031 | D | sin TRIADE_BACKUP_KEY ni TRIADE_BACKUP_KEY_FILE: no se crea ninguna copia y no se abre ninguna existente | operations | no | UNKNOWN | `complete_later` | P1 | La ausencia de clave bloquea correctamente; inventar o almacenar secretos está prohibido. |
| D056 | D | federated_exchange_log | federation | sí | 0 | `complete_later` | P2 | Tiene circuito estructural pero no actividad runtime observada. |
| D075 | D | federated_merge_log | federation | no | 0 | `merge_with_existing` | P2 | No tiene productor ni consumidor y se solapa con federated_exchange_log. |
| D076 | D | federated_merge_nodes | federation | no | 0 | `merge_with_existing` | P2 | Duplica federated_nodes, que sí contiene actividad runtime. |
| D082 | D | engineering_evolution_events | observability | sí | 2 | `complete_later` | P2 | Tiene productor y filas, pero ningún lector: actividad almacenada sin utilidad operativa. |
| D083 | D | evidence_remediation_audit | observability | sí | 479 | `complete_later` | P1 | Acumula 479 filas sin lector; la auditoría no es verificable desde una interfaz viva. |
| D084 | D | governed_research_runs | research | sí | 86 | `complete_later` | P2 | Hay 86 runs escritos y ningún consumidor, por lo que no informan decisiones posteriores. |
| D085 | D | hardware_senses | operations | sí | 293 | `complete_later` | P1 | Hay 293 muestras y ningún consumidor; medir sin actuar no demuestra salud. |
| D020 | E | relational_modulation_events | research | sí | 0 | `experimental_keep` | P3 | Código y tablas existen sin actividad productiva observada; no hay utilidad demostrada. |
| D021 | E | relational_modulation_states | research | sí | 0 | `experimental_keep` | P3 | Subsistema filosófico sin consumidor productivo ni filas runtime. |
| D051 | E | triade/core/hierarchical_pulse.py | research | no | UNKNOWN | `experimental_keep` | P3 | No tiene importador ni entrypoint vivo y no existe consumidor demostrado. |
| D066 | E | relational_modulation_events | research | sí | 0 | `experimental_keep` | P3 | Código y tablas existen sin actividad productiva observada; no hay utilidad demostrada. |
| D067 | E | relational_modulation_states | research | sí | 0 | `experimental_keep` | P3 | Subsistema filosófico sin consumidor productivo ni filas runtime. |
| D077 | E | meta_model_candidates | research | no | 0 | `experimental_keep` | P3 | Tabla sin productor ni consumidor y meta-orquestación no demostrada. |
| D078 | E | meta_model_decisions | research | no | 0 | `experimental_keep` | P3 | No hay circuito runtime ni consumidor real. |
| D079 | E | meta_model_evaluations | research | no | 0 | `experimental_keep` | P3 | Tabla desconectada sin mediciones runtime. |
| D080 | E | metabolic_config | research | no | 0 | `experimental_keep` | P3 | Tabla desconectada y sin consumidor; la metáfora no constituye capacidad. |
| D091 | E | self_improvement_canary_observation | self_improvement | sí | UNKNOWN | `experimental_keep` | P3 | Task type experimental nunca ejecutado productivamente. |
| D092 | E | self_improvement_evaluation | self_improvement | sí | UNKNOWN | `experimental_keep` | P3 | No hay ejecución runtime; código existente no demuestra reparación ni mejora. |

## Cambios, archivos y migraciones

- `scripts/build_phase_2_subsystem_triage.py`: política explícita, evidencia y generación reproducible.
- `artifacts/evolution/subsystem_triage.json`: contrato completo 72/72.
- `tests/test_phase_2_subsystem_triage.py`: gates arquitectónicos del inventario.
- Este informe: vista humana completa.
- Migraciones: ninguna. No se crean tablas ni filas para silenciar alertas.

## Pruebas, benchmark y regresiones

La suite específica valida cardinalidad, IDs, campos, owners, decisiones, duplicaciones, gate de activación y etiquetado experimental. Esta fase es de auditoría: la comparación aplicable exige conservar 72 → 72 observaciones.

Antes del PR se ejecutan compileall, Ruff, formato, mypy, suite global y suite específica. Sólo entonces puede declararse ausencia de regresiones.

## Criterio de cierre

- 72/72 observaciones revisadas y con exactamente una decisión.
- 72/72 con owner, razón, trabajo requerido y pruebas necesarias.
- 0 activaciones sin productor, consumidor, entrypoint, E2E y observabilidad.
- 0 experimentales presentados como vivos.
- 0 contadores reducidos; las 72 observaciones siguen trazadas.

## Riesgos, rollback, deuda restante y recomendación

El análisis estático identifica referencias pero no sustituye ejecución. `reachable=true` no significa usado ni útil. `complete_later` es backlog, no capacidad prometida.

Rollback: revertir los commits de esta fase; no hay migración ni mutación runtime. La fuente histórica permanece intacta.

Deuda restante: ejecutar cada trabajo en su fase y demostrar E2E antes de promover. La recomendación de merge se decide sólo tras gates terminales; nunca merge automático.

# Hallazgos del supervisor externo

Registra problemas comprobados, incluso cuando no sean la prioridad actual.

Todos los hallazgos de este ciclo salen de `artifacts/internal_graphs/`, generado
con `python scripts/build_internal_graphs.py`, y de la base viva
`triade/memory/triade.db` abierta en `mode=ro`. Ninguno proviene de documentación.

| ID | Fecha | Área | Hallazgo | Evidencia | Severidad | Estado | PR/Issue |
|---|---|---|---|---|---|---|---|
| F-000 | 2026-08-03 | Auditoría | Auditoría inicial ejecutada por Claude | este documento | Informativo | CLOSED | PR #69 |
| F-001 | 2026-08-03 | Supervisor | El agente exigía `scripts/build_internal_graphs.py` en su arranque obligatorio, y el script no existía ni en esta rama ni en `main`: el supervisor era inejecutable | `.claude/agents/triade-external-supervisor.md:23`; `git cat-file -e main:scripts/build_internal_graphs.py` falla | Alta | CLOSED | PR #69 |
| F-002 | 2026-08-03 | Memoria / Workers | `mission_planner` condicionaba `semantic_memory_governance` a `semantic_memory` (0 filas, tabla retirada) mientras la ingesta escribe en `semantic_documents` (186 filas `candidate`). La tarea nunca se encoló: 0 de 4 777 en `worker_tasks` y 0 de 5 452 en `autonomous_tasks` | `triade/workers/mission_planner.py:350`; consulta ro sobre la base viva | Alta | CLOSED | PR #69 |
| F-003 | 2026-08-03 | Observabilidad | `test_neural_graph_is_read_only` falla en la propia rama de PR #68: en `neuron_activity` el nodo del registro se identifica con `neuron_id`, así que origen y destino coinciden y la arista `uses_neuron` no se emite nunca | `triade/observability/neural_graph.py:113`; pytest sobre `origin/feat/internal-system-graphs` | Media | OPEN | PR #68 |
| F-004 | 2026-08-03 | Bodega / SQLite | 172 tablas se declaran o escriben en código y no existen en la base viva. Parte serán bases distintas y parte esquema muerto: hay que separarlas una a una antes de concluir nada | `artifacts/internal_graphs/table_graph.json` (`live=false`) | Media | OPEN | — |
| F-005 | 2026-08-03 | Qualia / Hipotálamo | 11 tablas vivas acumulan filas y no tienen ni un lector en el código: `metabolic_signals` 70 293, `qualia_states` 4 336, `qualia_central_packets` / `qualia_signals` / `qualia_storage_packets` 4 095 cada una, `runtime_health_snapshots` 1 362 | `table_graph.json`, estado `legacy` | Alta | OPEN | — |
| F-006 | 2026-08-03 | Educación | `neuron_education_applications`: 0 filas con 6 lectores y 5 escritores. El ciclo educativo no llega a aplicarse ni una vez | `table_graph.json`; base viva | Alta | OPEN | — |
| F-007 | 2026-08-03 | Workers | 9 tipos de tarea tienen handler y 0 ejecuciones: `bodega_global_review`, `federation_inbox_review`, `goal_install`, `goal_lora_train`, `self_improvement_canary_observation`, `self_improvement_evaluation`, `semantic_memory_governance`, `stable_consolidation_review`, `write_governed_text_artifact` | `worker_graph.json`, estado `disconnected` | Alta | PARTIAL | F-002 cierra uno |
| F-008 | 2026-08-03 | Entrypoints | 63 de 77 ficheros con guard `__main__` no los arranca nadie: ni Procfile, ni Dockerfile, ni systemd, ni workflows, ni `[project.scripts]` | `entrypoint_graph.json` | Media | OPEN | — |
| F-009 | 2026-08-03 | Código muerto | 54 módulos bajo `triade/` y `apps/` no tienen ningún importador (403 contando tests y scripts) | `import_graph.json`, estado `disconnected` | Media | OPEN | — |
| F-010 | 2026-08-03 | Código muerto | 4 441 de 6 753 símbolos no tienen ningún llamador demostrable estáticamente. El número es un techo, no una verdad: excluye llamadas dinámicas y descarta los homónimos | `call_graph.json` | Baja | OPEN | — |
| F-011 | 2026-08-03 | Pruebas | `triade/memory/schemas.sql` no declara `learning_evidence` ni `semantic_documents`. Con ese fixture el bloque baseline del planner aborta en la primera consulta y las pruebas ejercitan una ruta truncada sin decirlo | `tests/test_mission_planner.py:make_db`; excepción `no such table: learning_evidence` | Alta | OPEN | — |
| F-012 | 2026-08-03 | Observabilidad | El atlas físico recorría `node_modules`, `.git` y `runs/`: 96 036 nodos, de los cuales 74 665 eran salidas de ejecución. Inservible como mapa del sistema | `file_graph.json` antes del arreglo | Media | CLOSED | PR #69 |
| F-013 | 2026-08-03 | Observabilidad | El extractor de SQL aplicaba `FROM (\w+)` sobre el texto del fichero, así que `from pathlib import Path` producía una tabla llamada `pathlib`: 1 032 tablas falsas frente a 279 reales | `table_graph.json` antes del arreglo | Alta | CLOSED | PR #69 |
| F-014 | 2026-08-03 | Continuidad vital | El eslabón `Bodega` es el único de los once que aparece sin actividad sostenida: `episodic_memory` 241 filas, `semantic_memory` 0. La cadena llega hasta el almacén y ahí se estrecha | `vital_chain_graph.json` | Alta | OPEN | ligado a F-002 |
| F-016 | 2026-08-03 | Workers / Observabilidad | `_system_debt_scan` devolvía una frase fija sin escanear nada, durante 600 ejecuciones (265 en `worker_tasks`, 335 en `autonomous_tasks`), y publicaba esa frase en Qualia como si fuera una observación | `worker_loop.py:_system_debt_scan` antes del arreglo | Alta | CLOSED | PR #69 |
| F-017 | 2026-08-03 | Educación / Gates | Ninguna neurona está vacía: las 25 tienen training, evidencia o actividad (10 `stable`, 6 `experimental`, 6 `candidate_reviewable`, 3 `quarantined`). Lo que está vacío es el umbral: 8 currículos y 8 competencias frente a **0 certificaciones** y **0 aplicaciones**. Nada ha cruzado nunca el gate | consulta ro sobre `neurons`, `neuron_training`, `neuron_evidence`, `neuron_activity`, `neuron_certifications`, `neuron_education_applications` | Alta | OPEN | — |
| F-018 | 2026-08-03 | Aprendizaje | Tensión de diseño sin resolver: `_system_debt_scan` declara `truth: worker_self_observation_not_learning_evidence`, es decir que la autoobservación **no** es evidencia de aprendizaje. El operador pide que todo error y todo gate bajo se conviertan en conocimiento. Ambas cosas no pueden ser ciertas a la vez y la decisión no es técnica | `worker_loop.py`; `production_injection.PRODUCTION_STATES` | Alta | NEEDS_DECISION | — |
| F-015 | 2026-08-03 | Federación | `federated_merge_nodes` y `metabolic_config` no tienen lectores ni escritores en el código, y están vacías en la base | `table_graph.json` | Baja | OPEN | — |

## Reglas

- No registrar datos simulados.
- Diferenciar evidencia actual de evidencia histórica.
- No cerrar un hallazgo sin prueba o ejecución posterior.
- Mantener referencias a archivo, símbolo, tabla, run, log, prueba o artefacto.

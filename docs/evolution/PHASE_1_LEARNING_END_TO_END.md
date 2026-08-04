# Fase 1 — Aprendizaje end-to-end demostrable

## SHA base, rama y objetivo

- SHA base: `09b0248038cd4a2689355610cf823683a8a869e2`.
- Rama: `phase/01-learning-end-to-end`.
- Objetivo: demostrar necesidad → candidato → uso → medición → mejora → consolidación → recuperación → reutilización → mejora posterior.

## Estado inicial y hallazgo

El repositorio tenía código existente y pruebas por componentes para `LearningPipeline`, `LearningEvidenceBridge`, `RegressionGate` y `LearningRetriever`. Esas piezas eran alcanzables y estaban parcialmente probadas. No existía en esta rama una ejecución versionada que comparase un mismo benchmark sin candidato y con candidato, por split, y después recuperase el conocimiento consolidado en una decisión nueva.

Además, `LearningPipeline.consolidate()` capturaba la ausencia de Measurement Core y la sustituía por una nota de aprobación humana. Causa: una compatibilidad histórica confundía gobernanza humana con evidencia de mejora. Consecuencia: con suficientes contadores de uso, un humano podía consolidar sin comparación antes/después.

## Capacidad elegida

Se eligió **selección de contexto relevante** porque:

1. usa la ruta real de recuperación que inyecta candidatos antes de una decisión;
2. es determinista y reproducible sin depender de variación de un LLM;
3. permite medir exact match, latencia, memoria y falsos positivos;
4. permite separar train, validation, held-out, adversarial y regression;
5. no activa un módulo productivo nuevo ni toca identidad o seguridad.

El caso aprende un procedimiento de recuperación de `SQLite database locked`. El output esperado es si el contexto correcto debe seleccionarse (`relevant`) o no (`none`).

## Cambios y archivos

- `triade/learning/pipeline.py`: una aprobación ya no sustituye Measurement Core.
- `triade/learning/evidence_bridge.py`: gate optativo `generalization_required`; exige validation/held-out/regression completos, sin caída, y mejora fuera de train.
- `triade/learning/context_selection_benchmark.py`: carga, ejecución, medición, tratamiento, Regression Gate, consolidación y reutilización.
- `benchmarks/learning/context_selection/v1/*.json`: 10 casos versionados en cinco splits.
- `scripts/run_phase_1_learning_end_to_end.py`: reproducción aislada por defecto y generación del artefacto.
- `tests/test_learning_end_to_end_real.py`: siete pruebas end-to-end, negativas y de reproducción CLI.
- `artifacts/evolution/phase_1_results.json`: evidencia ejecutada.
- `.github/workflows/{ci,python-tests,tests,internal-graphs}.yml`: instalación del paquete y sus dependencias de desarrollo antes de ejecutar scripts por subproceso.
- `triade_omega.egg-info/SOURCES.txt`: manifiesto sincronizado; dos instalaciones editables consecutivas producen el mismo SHA-256.
- `triade/observability/{code_graph,file_graph,neural_graph,runtime_graph}.py`: correcciones tipadas requeridas por los gates, sin cambio de contrato.

Migración aditiva y reversible: `learning_evidence.generalization_required INTEGER NOT NULL DEFAULT 0`. No se elimina ni reinterpreta información existente. Rollback de código: revertir los commits de Fase 1; rollback de datos: la columna puede permanecer inerte con valor 0 sin alterar rutas previas.

## Benchmark y comparación

| Métrica | Baseline sin candidato | Tratamiento con candidato |
|---|---:|---:|
| Global | 0,30 | 1,00 |
| Train | 0,00 | 1,00 |
| Validation | 0,00 | 1,00 |
| Held-out | 0,00 | 1,00 |
| Adversarial | 0,50 | 1,00 |
| Regression | 1,00 | 1,00 |
| Tokens | 0 | 0 |
| Modelo | deterministic lexical retriever | deterministic lexical retriever |
| Latencia del run | 28,064 ms | 30,812 ms |
| Pico de memoria trazado | 58.441 bytes | 49.230 bytes |

La procedencia del candidato incluye suite, versión y SHA. El artefacto versionado se reprodujo sobre `d9dd29f418212dac220e616f34694d3fc91da1f0`. Entró mediante `ingest`, pasó por `evaluate` y `verify`, se usó en tres decisiones exitosas con referencias de evidencia, fue medido por Measurement Core, pasó un Regression Gate persistido y se consolidó con aprobación explícita. El runner se ejecutó después desde dos directorios distintos y conservó los mismos scores y los seis criterios de cierre.

## Reutilización posterior

Un run distinto consultó `¿Cómo recupero SQLite cuando aparece database locked?` después de la consolidación. La ruta normal experimental ya no lo seleccionaba por estado; la ruta explícita de conocimiento consolidado lo recuperó, cambió `none → relevant`, confirmó uso causal mediante evaluador determinista y persistió `learning_retrieval_decisions.audit_row_id = 1`.

Esto demuestra la capacidad acotada de selección de contexto del benchmark. No demuestra aprendizaje general, razonamiento autónomo ni mejora de cualquier otra capacidad.

## Pruebas y resultados

- Suite específica completa: 47 passed, 0 failed, 0 errors.
- Nueva suite: 7 passed, incluida reproducción independiente y dos ejecuciones CLI aisladas con los mismos scores y criterios de cierre.
- Casos negativos demostrados:
  - sin Measurement Core no consolida;
  - mejora solo train no avanza;
  - regresión crítica no avanza;
  - no medible queda `not_measurable`;
  - consolidado se recupera, cambia decisión y queda auditado.
- Gates de código en checkout limpio: `ruff check .`, `ruff format --check .` y `mypy triade`, todos terminales verdes; `compileall` también pasó.
- Suite completa aislada en GitHub Actions: 2.113 passed, 0 failed, 0 errors y 1 advertencia externa de deprecación. Los workflows Python Tests y Tríade Tests pasaron tanto en push como en PR.
- Suite integral de grafos local: 40 passed en 491,33 s. Internal Graphs pasó en CI en checkout limpio.
- Measurement Core, Regression Gate, matriz de concurrencia, frontend y Runtime Truth pasaron en CI sobre el SHA final del PR.

## Criterio de cierre

El artefacto ejecutado marca verdadero:

- `baseline_lt_candidate`;
- `held_out_not_worse`;
- `regression_pass`;
- `consolidated`;
- `recovered_later`;
- `later_use_improved`.

El criterio funcional y los gates de cierre de Fase 1 están satisfechos para la capacidad acotada. Esto demuestra una mejora gobernada y reproducible en **selección de contexto relevante**; no demuestra aprendizaje general de Tríade.

## Riesgos, deuda restante y recomendación

- El benchmark es pequeño y creado para esta fase; generaliza a held-out interno, no a distribución externa.
- La recuperación consolidada requiere declarar el estado permitido; la memoria semántica productiva viaja por otra ruta y no se afirma aquí como validada.
- El heartbeat y los 72 subsistemas siguen fuera del alcance de Fase 1; no se redujeron ni reclasificaron sus contadores.
- No se tocó `identity_core`, secretos, `.git`, permisos ni fronteras de seguridad.

Recomendación: **merge tras revisión humana del PR #72**. Los criterios funcionales, la reproducción, la suite global y los gates obligatorios pasan. No se hace merge automático; el rollback es revertir los commits pequeños de la fase y conservar la columna aditiva inerte.

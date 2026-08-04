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
- `scripts/run_phase_1_learning_end_to_end.py`: reproducción y generación del artefacto.
- `tests/test_learning_end_to_end_real.py`: seis pruebas end-to-end y negativas.
- `artifacts/evolution/phase_1_results.json`: evidencia ejecutada.

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

La procedencia del candidato incluye suite, versión y SHA. El artefacto final se reprodujo sobre `cc8d5b99d7a66c6557ee5e58e87b1eab861e59d6`. Entró mediante `ingest`, pasó por `evaluate` y `verify`, se usó en tres decisiones exitosas con referencias de evidencia, fue medido por Measurement Core, pasó un Regression Gate persistido y se consolidó con aprobación explícita.

## Reutilización posterior

Un run distinto consultó `¿Cómo recupero SQLite cuando aparece database locked?` después de la consolidación. La ruta normal experimental ya no lo seleccionaba por estado; la ruta explícita de conocimiento consolidado lo recuperó, cambió `none → relevant`, confirmó uso causal mediante evaluador determinista y persistió `learning_retrieval_decisions.audit_row_id = 1`.

Esto demuestra la capacidad acotada de selección de contexto del benchmark. No demuestra aprendizaje general, razonamiento autónomo ni mejora de cualquier otra capacidad.

## Pruebas y resultados

- Suite específica completa: 47 passed, 0 failed, 0 errors.
- Nueva suite: 6 passed, incluida reproducción independiente con los mismos scores y criterios de cierre.
- Casos negativos demostrados:
  - sin Measurement Core no consolida;
  - mejora solo train no avanza;
  - regresión crítica no avanza;
  - no medible queda `not_measurable`;
  - consolidado se recupera, cambia decisión y queda auditado.
- Gates globales heredados: Ruff y mypy ya fallaban antes del parche; véase baseline. No se ocultan ni se cuentan como arreglados.
- Suite completa: el intento aislado del SHA base quedó sin progreso más allá del 3 % y se interrumpió a 380,70 s; el intento inicial mezclado fue descartado. No se declara ausencia global de regresiones.

## Criterio de cierre

El artefacto ejecutado marca verdadero:

- `baseline_lt_candidate`;
- `held_out_not_worse`;
- `regression_pass`;
- `consolidated`;
- `recovered_later`;
- `later_use_improved`.

El criterio funcional de Fase 1 está satisfecho para la capacidad acotada. La fase completa permanece **bloqueada**: no hay resultado terminal de la suite global y Ruff, formato y mypy están rojos desde la baseline.

## Riesgos, deuda restante y recomendación

- El benchmark es pequeño y creado para esta fase; generaliza a held-out interno, no a distribución externa.
- La recuperación consolidada requiere declarar el estado permitido; la memoria semántica productiva viaja por otra ruta y no se afirma aquí como validada.
- Ruff (659 incidencias iniciales), formato (6 archivos iniciales), mypy (26 errores iniciales), heartbeat y 72 subsistemas siguen fuera del alcance de Fase 1.
- No se tocó `identity_core`, secretos, `.git`, permisos ni fronteras de seguridad.

Recomendación: **no merge**. Se abre únicamente PR draft para conservar revisión y evidencia. Antes de promoverlo deben obtenerse un `pytest -q` terminal y una política explícita para los gates heredados que ya fallan en `main`; nunca merge automático.

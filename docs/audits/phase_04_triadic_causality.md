# Fase 04 — causalidad triádica

Fecha UTC: 2026-07-29

Base: `de87714`

Estado: `completed`

## Contrato implementado

Cada `TriadeRunner.run()` produce ahora:

```text
triadic_cycle_trace.json
triadic_cycle_trace_verification.json
```

`TriadicCycleTrace` contiene entrada, señales, memoria recuperada, modulación del
Hipotálamo, regulación del Cristal, propuesta de Central, decisión de Safety,
acción final, referencias causales, contribución por componente y componentes
degradados. Las referencias enlazan artefactos mediante SHA-256 canónico. El
verificador rechaza hashes alterados, componentes ausentes o mezcla de run IDs.

La traza distingue degradación de ausencia: en la ejecución runtime de evidencia
Ollama no fue usado, por lo que `hypothalamus_model` y `central_model` figuran
degradados, mientras los fallbacks deterministas de ambos órganos sí produjeron
señales, plan y salida observables.

## Benchmark ablativo

Comando reproducible:

```bash
python scripts/run_phase_04_triadic_causality.py
```

Se ejecutaron tres tareas fijas, sin llamadas a modelos, en cinco variantes:

```text
full_triad
without_bodega
without_hypothalamus
without_crystal
without_semantic_recall
```

Las métricas son campos observables exactos: scores ya producidos por
`Verifier`, conteos y confianza de recall, decisión de Safety, tono, goal/número
de pasos/hash del plan, conteo de contradicciones, scores canónicos de utilidad y
trazabilidad, y estado numérico del Cristal. No existe evaluación humana ni
juicio de calidad generado por modelo.

## Resultado

Cada ablación cambió el resultado observable en 3/3 tareas:

| Ablación | Dimensiones con diferencia |
|---|---|
| sin Bodega | recall, planificación, Cristal |
| sin Hipotálamo | tono, planificación, Cristal; Safety en 1/3 |
| sin Cristal | planificación, estado del Cristal |
| sin recall semántico | recall, planificación; Cristal en 2/3 |

No se midió diferencia en coherencia, contradicciones ni quality canónica para
ninguna ablación. Tampoco cambió Safety al retirar Bodega, Cristal o recall
semántico en este conjunto. Esas contribuciones específicas **no quedan
demostradas** por este benchmark. La fase demuestra contribución causal de cada
componente en al menos una dimensión relevante; no afirma que cada componente
mejore todas las métricas.

## Evidencia

```text
artifacts/triade_verify/phase_04/triadic_causality.json
```

El bundle contiene los resultados completos por tarea y variante, los conteos
de diferencias por dimensión y una traza runtime verificada sin referencias
inválidas ni componentes ausentes.

## Validación

```text
python -m compileall -q triade apps scripts tests       pass
ruff format --check .                                   pass (734 archivos)
ruff check archivos nuevos Fase 4                       pass
pytest -q tests/test_triadic_cycle_trace.py              4 pass
pruebas dirigidas de runner/crystal/API                  21 pass
pytest -q                                               pass
pytest -q tests/operational_truth                        18 pass
python scripts/run_runtime_concurrency_test.py           pass
ruff check .                                            fail (813)
mypy triade                                             fail (224 en 68 archivos)
```

Concurrencia: 101 tareas contabilizadas, 90 `completed`, 11 `dead_letter`, cero
efectos duplicados, cero artefactos faltantes e integridad SQLite `ok`.

## Rollback

La reversión consiste en retirar la construcción de la traza del runner y los
dos artefactos adicionales; no hay migración de datos ni cambio destructivo. Las
trazas ya emitidas son evidencia append-only y no necesitan eliminación.

## Riesgos y deuda

- El benchmark determinista no prueba ventaja de calidad generativa con modelos
  reales; solo causalidad de las rutas canónicas. La orquestación medida se
  aborda en la Fase 11.
- Las dimensiones sin diferencia quedan abiertas para benchmarks futuros; no se
  cuentan como verificadas.
- Ruff y mypy globales continúan siendo deuda explícita de la Fase 18.

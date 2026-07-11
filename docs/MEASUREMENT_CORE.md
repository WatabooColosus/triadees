# Measurement Core · Tríade Ω

Measurement Core mide capacidades reproducibles antes de permitir que Tríade afirme que aprendió o mejoró.

## Flujo

```text
suite versionada
→ ejecución determinista
→ resultados por caso
→ score ponderado
→ baseline
→ candidato
→ comparación
→ improved | neutral | regressed | invalid
```

## Garantías

- sin shell ni red durante la evaluación;
- sin escritura en `identity_core`;
- sin consolidación de memoria estable;
- evidencia JSON bajo `runs/evaluations/<evaluation_id>/`;
- suites incompatibles producen `invalid`;
- una regresión en un caso crítico produce `regressed`.

## Ejecución local

```bash
PYTHONPATH=. python scripts/run_measurement_core.py
```

La suite inicial `core-safety-contracts` mide de forma local:

- detección de intentos de alterar identidad;
- normalización de candidatos;
- presencia de fuente trazable;
- gates mínimos de aprendizaje;
- autorización read-only de `pending_learning_review` en degradación.

## Evidencia

Cada ejecución genera:

- `suite.json`;
- `evaluation.json`;
- `baseline.json` cuando se crea baseline.

La integración con `LearningPipeline` pertenece a la Fase 2 y no se habilita hasta que este núcleo permanezca verde y reproducible.

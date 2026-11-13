# Fase 13 — LoRA y serving canary

Fecha UTC: 2026-07-29

Base: `3628a85`

Estado: `partial`

El gate verifica hashes de todos los blobs, bundle, dataset `training_ready` y
uso `lora_training`, métricas OOD y olvido, límite de tráfico canary, evidencia
de observación, aprobación nominal, versión persistente y rollback.

Se cargó realmente `triade-continuity-canary` sobre
`Qwen/Qwen2.5-0.5B-Instruct` con PEFT/CUDA y se produjo una generación. El
artifact tiene mejora de validation loss y no presenta regresión de forgetting.
La activación fue bloqueada porque no se suministró un aprobador nominal. No se
inventó aprobación ni se envió tráfico de producción.

## Reproducción

```bash
pytest -q tests/test_lora_serving_governance.py tests/test_real_lora_trainer.py
python scripts/run_phase_13_lora_canary.py
```

Evidencia: `artifacts/triade_verify/phase_13/lora_canary.json`.

Pendiente para cierre: aprobación humana nominal, ventana de tráfico canary
controlado y retiro seguro posterior. El entrenamiento nunca activa un adapter
automáticamente.

## Validación ejecutada

```text
python -m compileall -q triade apps scripts tests                   PASS
ruff check (archivos de fase)                                       PASS
ruff format --check .                                               PASS (772 files)
pytest -q tests/test_lora_serving_governance.py                      PASS (4)
pytest (LoRA governance/trainer/serving)                             PASS (11)
pytest -q tests/operational_truth                                   PASS (18)
python scripts/run_runtime_concurrency_test.py                      PASS
python scripts/run_phase_13_lora_canary.py                          PASS
```

El canary real tardó 12,771.81 ms, cargó el blob hasheado y mantuvo
`production_share: 0.0`. La suite global completa no se repitió en esta fase;
la última ejecución integral verde corresponde al commit de Fase 12.

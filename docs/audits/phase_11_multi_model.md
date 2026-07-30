# Fase 11 — orquestación multi-modelo medida

Fecha UTC: 2026-07-29

Base: `3331e84`

Estado: `completed` local runtime

Se implementaron los roles planner, coder, critic, evaluator, embedding, vision
y summarizer, una matriz explícita de calidad/latencia/VRAM/RAM/disponibilidad/
privacidad/contexto, selección explicable, fallback, señal de descarga GPU,
gate A/B, adopción y rollback.

El 2026-07-30 se ejecutó un A/B real contra `qwen3:4b` como baseline único para
los siete roles. El candidato usó `qwen3:4b` para planner/critic/evaluator,
`qwen2.5-coder:3b` para coder, `nomic-embed-text` para embedding, `gemma3:4b`
para visión y `qwen3:1.7b` para resumen. Todos fueron servidos por Ollama local.

La evaluación determinista comprobó contratos JSON, ranking semántico y una
imagen PNG roja conocida. Un sampler midió latencia wall-clock, RSS de Ollama y
VRAM con `nvidia-smi` mientras cada inferencia estaba activa. El baseline obtuvo
calidad 0.6786 y coste 4580.588; el routing obtuvo calidad 0.9643 y coste
5965.055, una razón de coste 1.302. El gate predefinido permite adopción por una
mejora de calidad mínima 0.10 solo si la razón de recursos no supera 2.0.

La mejora de calidad fue 0.2857 dentro del presupuesto, por lo que el routing se
activó en `triade/models/active_routing.json`. El router solo acepta el manifiesto
si está `active`, tiene evidencia, el modelo está instalado y cabe en hardware.
Cada decisión incluye el SHA-256 del benchmark. El rollback monomodelo está en
`active_routing.rollback.json` y se probó mediante escritura atómica.

## Reproducción

```bash
pytest -q tests/test_measured_model_orchestration.py
python scripts/run_phase_11_multi_model.py
```

Evidencia: `artifacts/triade_verify/phase_11/multi_model.json`.

La evidencia exacta está en `artifacts/triade_verify/phase_11/multi_model.json`,
SHA-256 `43121b70b8c8fa0bbb52bcc593be90ef9fe9f5ff9c7212b8c02a2df7ea2a1f21`.

## Validación ejecutada

```text
python -m compileall -q triade apps scripts tests             PASS
ruff check (archivos de fase)                                 PASS
ruff format --check .                                         PASS (764 files)
mypy triade/models/measured_orchestration.py                   PASS
pytest -q tests/test_measured_model_orchestration.py           PASS (5)
pytest -q tests/test_model_router.py tests/test_auto_model_selection.py
                                                              PASS
pytest -q                                                     PASS
pytest -q tests/operational_truth                             PASS (18)
python scripts/run_runtime_concurrency_test.py                PASS
```

Validación adicional: A/B real ejecutado, siete rutas runtime verificadas,
adopción medida aplicada y rollback atómico probado. Web y Ollama respondieron
HTTP 200 después del benchmark.

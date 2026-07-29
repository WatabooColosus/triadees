# Fase 11 — orquestación multi-modelo medida

Fecha UTC: 2026-07-29

Base: `3331e84`

Estado: `partial`

Se implementaron los roles planner, coder, critic, evaluator, embedding, vision
y summarizer, una matriz explícita de calidad/latencia/VRAM/RAM/disponibilidad/
privacidad/contexto, selección explicable, fallback, señal de descarga GPU,
gate A/B, adopción y rollback.

El entorno contiene el binario Ollama, pero el endpoint local no está activo y
no hay modelos verificables. `scripts/run_phase_11_multi_model.py` registra el
fallo exacto y rechaza la adopción. No se ejecutó ni se inventó un benchmark A/B
de modelos reales; por ello esta fase no está runtime verified.

## Reproducción

```bash
pytest -q tests/test_measured_model_orchestration.py
python scripts/run_phase_11_multi_model.py
```

Evidencia: `artifacts/triade_verify/phase_11/multi_model.json`.

Para cerrar la fase se necesitan al menos dos modelos reales disponibles y un
A/B por rol contra el baseline monomodelo. Solo se permite adopción si conserva
calidad y reduce recursos, o si mejora calidad bajo el presupuesto documentado.

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

La implementación y regresión son verdes. El resultado funcional continúa
`partial` exclusivamente porque no hubo modelos reales disponibles para el A/B.

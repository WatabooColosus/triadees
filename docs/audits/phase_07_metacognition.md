# Fase 07 — metacognición calibrada

Fecha UTC: 2026-07-29

Base: `21ce3e2`

Estado: `completed`

## Implementación

El `CapabilityRegistry` existente continúa siendo la autoridad de definición,
versionado, contratos, permisos y rollback. La migración aditiva 023 incorpora
su capa de awareness/calibración con los estados:

```text
available degraded unavailable unverified quarantined
```

Cada perfil registra dependencias, recursos, utilidad, riesgo y motivo. Antes de
ejecutar, `predict()` guarda probabilidad, razones y recursos. Los estados limitan
la confianza máxima: degraded 0.70, unavailable 0.05, unverified 0.30 y
quarantined 0. Un resultado post-ejecución requiere evidencia; los fallos,
además, una categoría canónica.

Taxonomía inicial:

```text
dependency_unavailable resource_exhausted permission_denied timeout
invalid_input postcondition_failed unknown
```

El historial permite calcular Brier, expected calibration error, accuracy,
false-confidence rate y unknown-detection rate. El gap detector selecciona
capacidades no disponibles/verificadas y las ordena por `utility * (1-risk)`;
esto es una recomendación, no aprendizaje ni promoción automática.

## Calibración runtime

```bash
python scripts/run_phase_07_metacognition.py
```

Se registraron antes de ejecución diez predicciones de 0.80, con ocho outcomes
independientes positivos, más dos probes de dependencia unavailable. Resultado:

```text
sample size: 12
Brier score: 0.13375
ECE: 0.0083333333
success prediction accuracy: 0.8333333333
false confidence rate: 0.0
unknown detection rate: 1.0
bucket 80 %: observed 80 %, tolerance ±5 %
```

Este resultado demuestra calibración en un bucket controlado pequeño; no debe
extrapolarse a todas las capacidades hasta acumular outcomes reales por dominio.

## Tests y evidencia

```text
pytest -q tests/test_metacognition.py                   4 pass
python scripts/run_phase_07_metacognition.py            5/5 pass
pytest -q                                               pass
pytest -q tests/operational_truth                        18 pass
python scripts/run_runtime_concurrency_test.py           pass
ruff format --check .                                   pass (748 archivos)
ruff check .                                            fail (813)
mypy triade                                             fail (224 en 68 archivos)
```

Artefacto:

```text
artifacts/triade_verify/phase_07/metacognition.json
```

## Rollback

La migración 023 solo crea tablas e índice. La capa puede desactivarse sin
alterar definiciones del Capability Registry ni outcomes de ejecución. El
historial no se borra automáticamente.

## Riesgos y deuda

- La muestra de calibración es pequeña y sintética-controlada, aunque los
  outcomes son registrados separadamente de las predicciones.
- Falta acumulación runtime longitudinal y calibración por capacidad/dominio.
- El gap detector no lanza research ni learning por sí solo; esas conexiones se
  gobiernan en Fases 8 y 9.
- Ruff/mypy globales permanecen para Fase 18.

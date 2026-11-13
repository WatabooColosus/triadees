# Fase 12 — neuronas certificables

> **Documento histórico.** Describe una fase `completed` el 2026-07-29 y sigue
> siendo su registro fiel. El instrumento que ejecutó —`NeuronCertifier`,
> `scripts/run_phase_12_neuron_certification.py`— se retiró el 2026-08-08 junto
> con la tabla `neuron_certifications`: el juicio sobre `stable` lo hace hoy
> `triade/core/stable_neuron_audit.py` sobre evidencia medida. Los comandos de
> «Reproducción» ya no existen. Las 13 transiciones que produjo se conservan en
> `neuron_certification_transitions`. Motivo y contraste de los dos contratos en
> [`docs/debt/NEURON_CERTIFICATION_CONTRACT.md`](../debt/NEURON_CERTIFICATION_CONTRACT.md).

Fecha UTC: 2026-07-29

Base: `7b8361b`

Estado: `completed`

El gate canónico exige manifest con mission, domain, allowed sources/actions,
benchmarks, baseline, evidencia, limitaciones, rollback, confianza, revisión,
owner y versión. `stable` requiere además benchmark, evaluación independiente,
regresión, rollback, reinicio y evidencia completa.

La base runtime contenía 13 neuronas `stable`. Ninguna tenía manifest de
certificación, por lo que las 13 se pusieron en `quarantined`. No se borró
historial. Antes del cambio se creó un backup SQLite con SHA-256; cada transición
conserva su rollback ref. El runner y el informe JSON enumeran cada bloqueo.

## Reproducción

```bash
pytest -q tests/test_neuron_certification.py
python scripts/run_phase_12_neuron_certification.py
```

Evidencia: `artifacts/triade_verify/phase_12/neuron_certification.json`.
Backup: `artifacts/triade_verify/phase_12/rollback/`.

Ninguna neurona queda declarada `stable` solo por actividad o etiqueta. Una
promoción futura debe insertar certificación completa y superar todos los gates.

## Validación ejecutada

```text
python -m compileall -q triade apps scripts tests                 PASS
ruff check (archivos de fase)                                     PASS
ruff format --check .                                             PASS (768 files)
pytest -q tests/test_neuron_certification.py                       PASS (3)
pytest (certificación, stable audit, promoción y fundacionales)    PASS (23)
pytest -q                                                         PASS
pytest -q tests/operational_truth                                 PASS (18)
python scripts/run_runtime_concurrency_test.py                    PASS
PRAGMA integrity_check (DB runtime después de cuarentena)          ok
```

El test de restore reproduce `stable` desde el backup. Un backup alterado es
rechazado por hash antes de restaurar.

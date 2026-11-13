# Fase 10 — Utility Ledger

Fecha UTC: 2026-07-29

Base: `ac74f46`

Estado: `completed`

`UtilityReceipt` separa explícitamente `activity`, `output`, `effect`, `utility`
y `learning`. Una mejora solo es válida con evidencia verificada, recibo de
efecto, delta positivo y cero regresiones. Heartbeat, pulse y maintenance nunca
pueden generar utilidad, aunque el productor intente etiquetarlos como tal.

El ledger conserva baseline, outcome, calidad, intervención humana, costos de
tiempo/CPU/GPU/memoria/storage/red, riesgo y referencias verificables. La
migración 026 es aditiva e idempotente; rollback consiste en dejar de escribir
la tabla, sin afectar recibos históricos.

## Ejecución reproducible

```bash
python scripts/run_phase_10_utility_ledger.py
pytest -q tests/test_utility_ledger.py
```

Evidencia runtime: `artifacts/triade_verify/phase_10/utility_ledger.json`.

## Validación ejecutada

```text
python -m compileall -q triade apps scripts tests       PASS
ruff check (archivos de fase)                           PASS
ruff format --check .                                   PASS (760 files)
pytest -q tests/test_utility_ledger.py                   PASS (6)
pytest -q                                               PASS
pytest -q tests/operational_truth                       PASS (18)
python scripts/run_runtime_concurrency_test.py          PASS
```

La prueba de concurrencia registró 101 tareas, 90 efectos, cero efectos
duplicados, cero artifacts ausentes e integridad SQLite `ok`. Los gates
estáticos globales continúan pendientes por deuda heredada y no se declaran
aprobados.

## Límites

Los costos son campos medidos por el productor; esta fase valida su contrato,
no añade todavía instrumentación uniforme a todos los ejecutores. La
restauración real y sus mediciones se prueban en la Fase 16.

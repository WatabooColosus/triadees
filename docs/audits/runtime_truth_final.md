# Runtime truth stabilization — estado verificable

Fecha: 2026-07-29 UTC  
Rama: `codex/runtime-truth-stabilization`  
Base: `4c18120525b039b4b6c66703a07b829b01d8e3f0`  
Último commit evaluado: `f7b181f38c4a18fa1d7db1a178a6bf460d21ac01`

## Estado

`partial_safe`

Las fases 1–17 están implementadas en commits independientes y sus pruebas
relacionadas están verdes. La fase 18 no está cerrada: el repositorio conserva
284 errores Ruff y 215 errores mypy. Por la regla de no avanzar con CI roja no
se inició la validación real de 24 horas ni el retiro de la cola legacy.

## Evidencia ejecutada

- `python -m compileall -q triade`: correcto.
- `pytest -q`: suite completa correcta el 2026-07-29, después de las correcciones
  funcionales y de Ruff.
- `pytest -q tests/operational_truth`: 15 pruebas correctas.
- `ruff format --check .`: 716 archivos formateados correctamente.
- `ruff check .`: falló con 284 incidencias: 256 `BLE001` y 28 `S110`.
  Las 74 incidencias de formato, configuración mutable, subprocess, fechas y
  flujo estructural registradas en el corte anterior fueron corregidas y
  verificadas sin desactivar reglas.
- `mypy triade --no-error-summary`: falló con 215 errores.
- Prueba real de concurrencia: 101 tareas, 111 intentos de enqueue, 3 workers,
  90 completadas, 11 `dead_letter`, cero efectos duplicados, cero artefactos
  ausentes y `PRAGMA integrity_check=ok`. Detalle en
  `docs/audits/runtime_concurrency_report.md`.

## Invariantes implementadas

- Estados terminales veraces mediante `ExecutionResult`.
- Timeout cancelable y cuarentena de resultados tardíos.
- Renovación de leases y fencing token monotónico.
- Ejecución canónica v2 y reconciliación de la cola legacy.
- Artefactos atómicos con hashes y manifiesto.
- Despacho gobernado desde planes de Central.
- Recibos verificables de efecto, evidencia y aprendizaje.
- Uso de recursos distinguido como `measured`, `estimated` o `unavailable`.
- Cierre recuperable, rollback comprobable, locks y cancelación.
- Backpressure, justicia de cola y suite `operational_truth`.
- E2E gobernado de escritura, verificación y rollback.

## Bloqueos y trabajo no ejecutado

- CI no puede declararse verde mientras falle Ruff.
- Mypy global continúa como deuda explícita; las áreas nuevas sí están tipadas.
- La prueba de 24 horas no fue ejecutada y no se presenta como completada.
- La retirada de legacy no comenzó porque depende de la prueba de estabilidad.
- No se hizo push, merge, despliegue ni reinicio de producción.

## Reanudación exacta

```bash
git switch codex/runtime-truth-stabilization
ruff check .
mypy triade
pytest -q
pytest -q tests/operational_truth
python scripts/run_runtime_concurrency_test.py
```

Después de dejar CI verde, ejecutar la validación durante 24 horas reales con
`scripts/run_24h_runtime_validation.py`; solo un informe producido por esa
ejecución puede habilitar la fase de retirada legacy.

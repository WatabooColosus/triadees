# Fase 18 — calidad estática y CI

Fecha UTC: 2026-07-30

Base: `1cfa114`

Estado: `partial`

CI ahora declara matrices Python 3.11/3.12 y gates obligatorios para compileall
completo, Ruff check/format, mypy, pytest, operational truth, migraciones,
concurrencia y seguridad. Mypy dejó de ser `continue-on-error`; los artefactos
se publican aun ante fallo.

## Verdad local

Ejecución local del 30 de julio de 2026:

- `compileall`: aprobado.
- `ruff format --check .`: 792 archivos ya formateados.
- suite focal de migraciones y seguridad: 35 pruebas aprobadas.
- `pytest -q`: aprobado al 100 %, código de salida 0; una advertencia de
  deprecación de Starlette ajena al código del repositorio.
- `tests/operational_truth`: 18 pruebas aprobadas.
- concurrencia real reducida: 111 encolados, 101 filas, 90 efectos, 11
  `dead_letter`, cero efectos duplicados, cero artefactos ausentes, una lease
  recuperada, integridad SQLite `ok` y todas las tareas contabilizadas.
- web pública: HTTP 200.
- Ollama local: HTTP 200.

La anomalía local de permisos hacía que Ruff reportara 536 `EXE002` aunque el
índice Git ya registra esos archivos como `100644`; se normalizó el workspace.
Quedan 271 errores Ruff reales: 247 catches amplios y 24 catches silenciosos.
Mypy conserva 224 errores en 68 archivos. No se desactivó ninguna regla ni se
añadieron ignores/noqa/skips/xfail.

Por tanto el gate local no está verde y, como no hubo push, GitHub Actions no se
ha ejecutado sobre estos commits. Esta fase no puede ser `completed`.

## Gates reproducibles

```bash
python -m compileall -q triade apps scripts tests
ruff check .
ruff format --check .
mypy triade
pytest -q
pytest -q tests/operational_truth
python scripts/run_runtime_concurrency_test.py
```

Branch protection está documentada en `docs/operations/branch_protection.md`.
Pendiente: resolver por fronteras los 224 errores mypy y revisar semánticamente
271 manejadores de excepción; luego ejecutar y confirmar CI remota.

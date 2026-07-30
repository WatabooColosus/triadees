# Fase 18 — calidad estática y CI

Fecha UTC: 2026-07-30

Base de validación local: `9d179bd`

Estado: `partial` (`CI final SHA pending`)

CI ahora declara matrices Python 3.11/3.12 y gates obligatorios para compileall
completo, Ruff check/format, mypy, pytest, operational truth, migraciones,
concurrencia y seguridad. Mypy dejó de ser `continue-on-error`; los artefactos
se publican aun ante fallo.

## Verdad local

Ejecución local del 30 de julio de 2026:

- `compileall`: aprobado.
- `ruff check .`: cero incidencias.
- `ruff format --check .`: 802 archivos ya formateados.
- `mypy triade`: cero errores en 324 archivos fuente.
- suite focal runtime/operational: 28 pruebas aprobadas.
- `pytest -q`: aprobado al 100 %, código de salida 0; una advertencia de
  deprecación de Starlette ajena al código del repositorio.
- `tests/operational_truth`: 18 pruebas aprobadas.
- concurrencia real reducida: 111 encolados, 101 filas, 90 efectos, 11
  `dead_letter`, cero efectos duplicados, cero artefactos ausentes, una lease
  recuperada, integridad SQLite `ok` y todas las tareas contabilizadas.
- web pública: HTTP 200.
- Ollama local: HTTP 200.

Las 271 incidencias Ruff y los 224 errores mypy del baseline se resolvieron sin
desactivar reglas ni añadir ignores/noqa/skips/xfail. Un checkout limpio reveló
un bit ejecutable ausente en el rollback de routing; se corrigió en `00a05aa`.
Sobre ese SHA, Runtime Truth CI, Tríade Tests y Measurement Core finalizaron en
`success`.

El SHA `9d179bd` está publicado y sus workflows están en curso. La fase no será
`completed` ni `ci_verified=true` hasta que todos terminen en verde. Además, la
protección de `main` está documentada pero la API de GitHub confirmó que todavía
no está aplicada; se mantiene pendiente para no bloquear la secuencia de commits
directos expresamente solicitada.

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

Branch protection y su estado real están documentados en
`docs/operations/branch_protection.md`. Pendiente: confirmar CI remota sobre el
SHA final y activar/verificar la protección cuando termine la secuencia de
publicación directa.

# Operación de TRIADE-VERIFY-v1

## Precondiciones

Trabajar con Git limpio, registrar rama/SHA y conservar fuera del repositorio las
claves de backup y autenticación. La ejecución no hace push, despliegue ni activa
adaptadores LoRA.

## Gates locales

```bash
python -m compileall -q triade apps scripts tests
ruff check .
ruff format --check .
mypy triade
pytest -q
pytest -q tests/operational_truth
python scripts/run_runtime_concurrency_test.py
python scripts/record_ci_evidence.py
python scripts/run_triade_verify.py
```

El último comando crea `artifacts/triade_verify/<timestamp>/` con manifest,
reporte y evidencia copiada. Un bundle ausente o cuyo `passed` no sea el booleano
`true` no abre su gate.

## Long run

```bash
python scripts/run_24h_runtime_validation.py
python scripts/run_72h_runtime_validation.py
python scripts/run_triade_chaos_validation.py
```

No reducir `--duration`, alterar relojes ni presentar una prueba corta como 24/72
horas. Ejecutar los fallos destructivos solo en una ventana aislada y autorizada.

## Recuperación

Antes de cada ventana, crear y verificar un backup cifrado. Restaurar primero en
sandbox y verificar integridad SQLite, identity hash, hashes de artefactos,
memoria semántica y estados de tareas. No sobrescribir producción sin aprobación
explícita.

## Estados

- `PARTIAL_SAFE`: faltan uno o más gates obligatorios.
- `VERIFIED_LOCAL`: todos los gates locales, long-run y CI están verificados.
- `VERIFIED_FEDERATED`: lo anterior más federación verificable.

El corte 2026-07-30 permanece `PARTIAL_SAFE` porque
`long_run_verified=false` y `ci_verified=false`.

Objetivos provisionales y condiciones de aprobación:
`docs/operations/production_reliability_targets.md`.

# Fase 03 — continuidad identitaria verificable

Fecha UTC: 2026-07-29  
Base: `ee87ffd7e5263a55a953491cfc64748a24cb943d`  
Estado: `completed`

## Alcance implementado

- `IdentityManifest` calcula hashes SHA-256 canónicos de la constitución y de
  las filas de `identity_core`, además de registrar versión identitaria,
  versión de esquema y versión de políticas.
- La migración SQLite `020_identity_continuity.sql` crea un ancla única y un
  historial append-only de verificaciones. La migración no consulta ni modifica
  `identity_core`.
- La primera verificación establece el ancla. Reinicios posteriores comparan el
  manifiesto actual con el ancla y con el run anterior.
- Cualquier mismatch entra en `degraded_safe`, registra las dimensiones
  divergentes y, en el lifespan de la API, impide iniciar workers y servicios
  background.
- La migración del ancla exige `approved_by`, motivo explícito y crea primero un
  backup SQLite. No existe promoción automática del manifiesto esperado.
- La restauración incluida en esta fase solo opera sobre un destino sandbox
  inexistente, ejecuta `PRAGMA integrity_check` y vuelve a verificar el hash de
  identidad. Nunca pisa producción.
- Se añadió `GET /api/identity/verify` y
  `python triade_digimon.py identity verify`.

## Protección de `identity_core`

El verificador únicamente ejecuta `SELECT` sobre `identity_core`. Safe File Ops
clasifica cualquier ruta que contenga `identity_core` como prohibida. Las
pruebas también comparan las filas antes y después de ejecutar la migración de
continuidad y registrar un nodo federado. Se reejecutaron las suites existentes
que demuestran invariancia ante workers y el learning pipeline.

## Evidencia runtime reproducible

Comando:

```bash
python scripts/run_phase_03_identity_continuity.py
```

Artefacto:

```text
artifacts/triade_verify/phase_03/identity_continuity.json
```

Resultado observado: 8/8 checks aprobados. El segundo arranque conservó el
hash; la alteración directa de `entity_name` fue detectada; el estado resultó
`degraded_safe`; el backup restauró en sandbox con integridad SQLite `ok` y el
hash esperado, sin sobrescribir producción.

## Validaciones ejecutadas

```text
python -m compileall -q triade apps scripts tests       pass
ruff format --check .                                   pass (729 archivos)
pytest -q                                               pass
pytest -q tests/operational_truth                       pass (18)
pruebas dirigidas identidad/seguridad                   pass (18)
python scripts/run_runtime_concurrency_test.py          pass
mypy triade/core/identity_continuity.py                 pass
ruff check sobre archivos nuevos de Fase 3              pass
ruff check .                                            fail (813 errores preexistentes)
mypy triade                                             fail (224 errores en 68 archivos)
```

Concurrencia observada: 101 filas, 90 `completed`, 11 `dead_letter`, cero
efectos duplicados, cero artefactos ausentes, una lease recuperada e integridad
SQLite `ok`.

## Migración y rollback

La migración 020 es idempotente (`CREATE TABLE/INDEX IF NOT EXISTS`) y no altera
tablas previas. El rollback operacional consiste en restaurar el backup creado
por `migrate_anchor` en sandbox, verificarlo y seguir el procedimiento humano de
restauración; no se ofrece un borrado automático de historial. Antes de aceptar
una nueva versión de constitución, políticas, esquema o identidad se requiere
una migración nominal explícita.

## Riesgos y deuda restante

- Ruff global (813) y mypy global (224) siguen rojos; pertenecen a la deuda de
  calidad estática que no se declara cerrada en esta fase.
- La política de restauración de producción, cifrado y retención corresponde a
  la Fase 16; aquí solo se demuestra restore aislado y verificable.
- El endpoint registra una verificación en el log, pero no altera el ancla ni
  `identity_core`; "read-only" se refiere a la identidad canónica.
- La identidad continua queda verificada localmente. Esto no demuestra AGI,
  conciencia ni autosuficiencia.

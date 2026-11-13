# Fase 16 — recuperación y backups

Fecha UTC: 2026-07-30

Base de ejecución: `00a05aa`

Estado: `completed`

El backup usa Fernet con `TRIADE_BACKUP_KEY` o un
`TRIADE_BACKUP_KEY_FILE` de permisos `0600`, snapshot transaccional
SQLite, gzip, hash del ciphertext y de la DB restaurada. La verificación cubre
integridad, anchor de identidad, memoria semántica, estados de tareas y refs de
artifacts. Restore sandbox no pisa producción; restore productivo exige
aprobación y genera primero backup cifrado.

Se añadió cooldown contra snapshot storms, métricas de espacio y retención
diaria/semanal. La retención mueve excedentes a cuarentena en vez de borrarlos.
Clave incorrecta, ciphertext truncado, hash alterado e identity anchor ausente se
exponen en la evidencia y nunca se presentan como restore válido.

El worker canónico ejecuta el drill semanal después de crear y verificar un
backup nuevo. Un backup solicitado durante cooldown queda `blocked` con razón
`backup_cooldown_active`; no se declara `completed` ni se fabrica recibo. La
migración idempotente `031_restore_drills.sql` conserva el ledger de simulacros,
verificación semántica y crecimiento de almacenamiento.

Los snapshots de recuperación mantienen 10 copias recientes en claro. Los más
antiguos se comprimen en `artifacts/recovery/quarantine`, con hash del original,
hash del archivo y manifiesto recuperable. El original solo se retira después de
descomprimir y comprobar su hash. La restauración de un archivo en cuarentena
también valida integridad SQLite antes del reemplazo atómico del destino.

## Reproducción

```bash
pytest -q tests/test_encrypted_backup_recovery.py tests/test_p0_p1_runtime_governance.py
python scripts/run_phase_16_recovery.py
TRIADE_BACKUP_KEY_FILE=/ruta/0600/triade_backup.key python scripts/runtime_backup.py
```

Evidencia: `artifacts/triade_verify/phase_16/recovery.json`.

No se ejecutó restore sobre la DB productiva; requiere aprobación humana
explícita. La clave efímera del runner no se escribe en el artifact.

## Resultado runtime

La snapshot cifrada fue de 77,594,624 bytes. El drill real
`restore-drill-0411c0aabe1045e7` restauró exclusivamente a sandbox, conservó el
anchor de identidad
`311b12b1b19289dac19067ebad1958373fbdcd53102b781f44b7776069ffcbd8`,
verificó 455 referencias de artifacts sin fallos y los estados de tareas
(`blocked`, `completed`, `observed`, `running`, `skipped`); integridad `ok` y
`production_overwritten=false`. El conteo de memoria semántica fue cero y se
registra así, sin presentarlo como recuperación de memorias inexistentes.

La ventana de retención archivó 446 snapshots adicionales, recuperó
30,064,773,059 bytes y terminó con 10 snapshots planos y 503 archivos
recuperables en cuarentena. El directorio bajó de 35 GB observados a 5.1 GB. Se
restauró una copia archivada separada con hashes válidos e integridad `ok`.

```text
pytest (encrypted backup/effect receipts/governance)            PASS (14)
pytest (recovery/watchdog/encrypted backup)                      PASS (14)
pytest -q tests/operational_truth                               PASS (18)
python scripts/run_runtime_concurrency_test.py                  PASS
ruff check (archivos de fase)                                   PASS
ruff format --check .                                           PASS (785 files)
python scripts/run_phase_16_recovery.py                         PASS
```

Durante la validación, web pública permaneció 200 y Ollama expuso seis modelos.

Limitación: no se ejecutó restore sobre producción, porque esa operación requiere
aprobación humana nominal. El drill periódico está automatizado, pero una sola
ejecución no demuestra por sí misma semanas de cumplimiento del calendario.

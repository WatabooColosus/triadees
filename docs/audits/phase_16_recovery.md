# Fase 16 — recuperación y backups

Fecha UTC: 2026-07-29

Base: `24886ec`

Estado: `completed`

El backup usa Fernet con `TRIADE_BACKUP_KEY` obligatoria, snapshot transaccional
SQLite, gzip, hash del ciphertext y de la DB restaurada. La verificación cubre
integridad, anchor de identidad, memoria semántica, estados de tareas y refs de
artifacts. Restore sandbox no pisa producción; restore productivo exige
aprobación y genera primero backup cifrado.

Se añadió cooldown contra snapshot storms, métricas de espacio y retención
diaria/semanal. La retención mueve excedentes a cuarentena en vez de borrarlos.
Clave incorrecta, ciphertext truncado, hash alterado e identity anchor ausente se
exponen en la evidencia y nunca se presentan como restore válido.

## Reproducción

```bash
pytest -q tests/test_encrypted_backup_recovery.py tests/test_p0_p1_runtime_governance.py
python scripts/run_phase_16_recovery.py
```

Evidencia: `artifacts/triade_verify/phase_16/recovery.json`.

No se ejecutó restore sobre la DB productiva; requiere aprobación humana
explícita. La clave efímera del runner no se escribe en el artifact.

## Resultado runtime

La snapshot cifrada fue de 77,594,624 bytes. Restore sandbox conservó el anchor
de identidad, 410 refs de artifacts verificadas sin fallos y los estados de
tareas (`blocked`, `completed`, `observed`, `running`); integridad `ok`.

```text
pytest (encrypted backup/effect receipts/governance)            PASS (14)
pytest (recovery/watchdog/encrypted backup)                      PASS (11)
pytest -q tests/operational_truth                               PASS (18)
python scripts/run_runtime_concurrency_test.py                  PASS
ruff check (archivos de fase)                                   PASS
ruff format --check .                                           PASS (785 files)
python scripts/run_phase_16_recovery.py                         PASS
```

Durante la validación, web pública permaneció 200 y Ollama expuso seis modelos.

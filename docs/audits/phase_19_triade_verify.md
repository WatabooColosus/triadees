# Fase 19 — certificación TRIADE-VERIFY-v1

Fecha UTC: 2026-07-30

Base: `23a7d77`

Estado: `partial`

El certificador lee únicamente bundles runtime existentes cuyo campo `passed`
sea el booleano literal `true`, copia la evidencia y calcula SHA-256. Una prueba
ausente, ilegible o sin aprobación queda en `false`. La duración prolongada
exige al menos 72 horas reales y chaos completo; CI permanece falsa hasta tener
confirmación de GitHub Actions.

El resultado actual es `PARTIAL_SAFE`: las siete dimensiones respaldadas por
ejecuciones previas están verificadas, pero `long_run_verified` y `ci_verified`
siguen falsas. No corresponde emitir `VERIFIED_LOCAL`.

## Reproducción

```bash
python scripts/run_triade_verify.py
pytest -q tests/triade_verify
```

# Fase 19 — certificación TRIADE-VERIFY-v1

Fecha UTC: 2026-07-30

Base: `23a7d77`

Estado: `partial`

El certificador lee únicamente bundles runtime existentes cuyo campo `passed`
sea el booleano literal `true`, copia la evidencia y calcula SHA-256. Una prueba
ausente, ilegible o sin aprobación queda en `false`. La duración prolongada
exige reportes separados de 24 y 72 horas, reloj no comprimido, disponibilidad
mínima 99%, todos los invariantes P0 en sus umbrales y chaos completo.

CI solo se abre desde `runs/triade_verify_live/phase_18/ci.json` cuando el SHA coincide exactamente con
HEAD y Runtime Truth CI, Tríade Tests, Measurement Core y Python Tests constan
en `success`. `scripts/record_ci_evidence.py` consulta GitHub mediante `gh` y
sale con código distinto de cero si falta un workflow o sigue en curso.

La evidencia viva de chaos y 24/72 h también reside bajo
`runs/triade_verify_live/phase_17/`. Mantenerla fuera del índice evita que el
acto de registrar evidencia cambie el SHA probado; el bundle final conserva
copias y hashes SHA-256.

El resultado actual es `PARTIAL_SAFE`: las siete dimensiones respaldadas por
ejecuciones previas están verificadas, pero `long_run_verified` y `ci_verified`
siguen falsas. No corresponde emitir `VERIFIED_LOCAL`.

## Reproducción

```bash
python scripts/run_triade_verify.py
python scripts/record_ci_evidence.py
pytest -q tests/triade_verify
```

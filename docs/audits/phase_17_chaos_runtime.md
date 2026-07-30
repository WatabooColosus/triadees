# Fase 17 — chaos y operación prolongada

Fecha UTC: 2026-07-30

Base: `7e5af4a`

Estado: `partial`

Se crearon los runners de 24h y 72h con duración wall-clock real. Sus defaults
son exactamente 86,400 y 259,200 segundos; no aceleran ni comprimen tiempo. Una
prueba corta separada comprueba web, Ollama e integridad SQLite.

El chaos corto inyecta en recursos aislados kill worker/API/orphan, lease expiry,
stale fencing, late result, DB lock, port conflict, network outage y backup
failure. No mata la web ni Ollama productivos. Los fallos restantes se declaran
`not_executed` con motivo; no se presentan como aprobados.

## Reproducción

```bash
python scripts/run_triade_chaos_validation.py
python scripts/run_24h_runtime_validation.py
python scripts/run_72h_runtime_validation.py
```

Evidencia corta: `artifacts/triade_verify/phase_17/chaos_short.json` y
`runtime_short.json`.

Estado: `implementation_complete`, `long_run_pending`. No se verifican todavía
availability 24/72h, restart Ollama, disk pressure, watchdog, GPU unavailable,
low memory ni rollback 100% en una ventana completa.

## Validación ejecutada

```text
pytest -q tests/test_runtime_long_run.py tests/test_runtime_watchdog.py PASS (8)
python scripts/run_triade_chaos_validation.py                    PASS subset
24h runner --duration-seconds 10 (short separado)                PASS
pytest -q tests/operational_truth                               PASS (18)
python scripts/run_runtime_concurrency_test.py                  PASS
ruff check (archivos de fase) / format                          PASS
```

La ventana corta duró al menos 10.0 segundos reales, seis checkpoints, 100% de
availability, DB corruption 0, web 200 y Ollama 200. Esto no sustituye 24h.
